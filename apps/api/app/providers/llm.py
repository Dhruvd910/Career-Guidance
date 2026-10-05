"""The language model: one OpenAI-compatible implementation covers OpenRouter (the default),
OpenAI itself, and local servers such as llama.cpp's and Ollama's — only the base URL, key and
model differ, and those are config.

`chat()` returns the whole reply; `stream()` yields it as it is generated, which is what lets
MAYA start speaking after the first sentence instead of after the last.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from app.providers.http import ProviderError, client_for, send


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON text, exactly as the model wrote it


@dataclass(frozen=True)
class Usage:
    """What one call used: tokens, how many of the prompt's came from the provider's cache, and what
    it cost (OpenRouter reports it; None elsewhere). `model` is the one that answered — a fallback
    model if the first was unavailable."""

    model: str | None = None
    prompt_tokens: int = 0
    cached_tokens: int = 0
    completion_tokens: int = 0
    cost: float | None = None

    @classmethod
    def from_response(cls, data: dict[str, Any], model: str | None) -> "Usage | None":
        usage = data.get("usage")
        if not isinstance(usage, dict):
            return None
        details = usage.get("prompt_tokens_details") or {}
        return cls(model=data.get("model") or model, prompt_tokens=int(usage.get("prompt_tokens") or 0),
                   cached_tokens=int(details.get("cached_tokens") or 0),
                   completion_tokens=int(usage.get("completion_tokens") or 0),
                   cost=float(usage["cost"]) if usage.get("cost") is not None else None)

    def __add__(self, other: "Usage | None") -> "Usage":
        if other is None:
            return self
        cost = None if self.cost is None and other.cost is None else (self.cost or 0.0) + (other.cost or 0.0)
        return Usage(other.model or self.model, self.prompt_tokens + other.prompt_tokens,
                     self.cached_tokens + other.cached_tokens, self.completion_tokens + other.completion_tokens, cost)

    def as_dict(self) -> dict[str, Any]:
        return {"model": self.model, "tokens_in": self.prompt_tokens, "tokens_cached": self.cached_tokens,
                "tokens_out": self.completion_tokens, "cost_usd": round(self.cost, 6) if self.cost is not None else None}


@dataclass(frozen=True)
class Done:
    finish_reason: str | None = None
    usage: Usage | None = None


LLMEvent = TextDelta | ToolCall | Done

logger = logging.getLogger("app.llm")

# Generating a long reply can take a while; the read timeout is per chunk when streaming.
CHAT_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)


class LLMProvider(ABC):
    model_id: str

    @abstractmethod
    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                   json_mode: bool = False) -> dict[str, Any]:
        """The whole reply, as an OpenAI-style message: {role, content, tool_calls?}. json_mode
        asks for a single JSON object as the content (OpenAI-style response_format)."""

    @abstractmethod
    def stream(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> AsyncIterator[LLMEvent]:
        """TextDelta pieces as they're generated, then any ToolCalls (whole), then Done."""


def _log(name: str, usage: Usage | None) -> None:
    if usage is not None:
        from app.core import observability

        observability.record_llm(usage.model, usage.prompt_tokens, usage.cached_tokens, usage.completion_tokens, usage.cost)
        logger.info("llm %s model=%s in=%d cached=%d out=%d cost=%s", name, usage.model, usage.prompt_tokens,
                    usage.cached_tokens, usage.completion_tokens,
                    f"${usage.cost:.6f}" if usage.cost is not None else "n/a")


class OpenAICompatibleLLM(LLMProvider):
    """`extra`: fields added to every request — for OpenRouter, the data policy, fallback models and
    usage accounting (see registry.py)."""

    def __init__(self, base_url: str, model: str, api_key: str | None = None, *, name: str = "llm",
                 client: httpx.AsyncClient | None = None, extra: dict[str, Any] | None = None):
        self.base_url, self.model_id, self._api_key, self.name = base_url, model, api_key, name
        self._client = client
        self._extra = extra or {}
        self.last_usage: Usage | None = None  # of the most recent chat() call

    def _http(self) -> httpx.AsyncClient:
        return self._client or client_for(self.base_url)

    def _build(self, messages, tools, stream: bool, json_mode: bool = False):
        body: dict[str, Any] = {**self._extra, "model": self.model_id, "messages": messages}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if stream:
            body["stream"] = True
        headers = {"Content-Type": "application/json"}
        if self._api_key:  # local servers usually need none
            headers["Authorization"] = f"Bearer {self._api_key}"
        http = self._http()
        return lambda: http.build_request("POST", "chat/completions", json=body, headers=headers,
                                          timeout=CHAT_TIMEOUT)

    async def chat(self, messages, tools=None, json_mode=False):
        response = await send(self._http(), self._build(messages, tools, stream=False, json_mode=json_mode),
                              provider=self.name)
        try:
            data = response.json()
            message = data["choices"][0]["message"]
        except (ValueError, KeyError, IndexError) as e:
            raise ProviderError(self.name, f"unexpected reply: {response.text[:200]}") from e
        self.last_usage = Usage.from_response(data, self.model_id)
        _log(self.name, self.last_usage)
        return message

    async def stream(self, messages, tools=None):
        response = await send(self._http(), self._build(messages, tools, stream=True), provider=self.name,
                              stream=True)
        calls: dict[int, dict[str, str]] = {}
        finish_reason, usage = None, None
        try:
            async for line in response.aiter_lines():
                # Server-sent events: "data: {json}" lines; ":" lines are keep-alive comments.
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                if "error" in chunk:
                    raise ProviderError(self.name, str(chunk["error"].get("message", chunk["error"])))
                usage = Usage.from_response(chunk, self.model_id) or usage  # in the last chunk, when asked for
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    if delta.get("content"):
                        yield TextDelta(delta["content"])
                    for part in delta.get("tool_calls") or []:
                        # A call arrives in fragments: id and name first, then its arguments piece by piece.
                        index = part.get("index", 0)
                        call = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                        function = part.get("function") or {}
                        if part.get("id"):
                            call["id"] = part["id"]
                        if function.get("name") and not call["name"]:
                            call["name"] = function["name"]
                        call["arguments"] += function.get("arguments") or ""
                    finish_reason = choice.get("finish_reason") or finish_reason
        except httpx.HTTPError as e:
            raise ProviderError(self.name, f"stream broke off: {type(e).__name__}: {e}") from e
        finally:
            await response.aclose()
        for index in sorted(calls):
            call = calls[index]
            yield ToolCall(id=call["id"] or f"call_{index}", name=call["name"], arguments=call["arguments"] or "{}")
        _log(self.name, usage)
        yield Done(finish_reason, usage)
