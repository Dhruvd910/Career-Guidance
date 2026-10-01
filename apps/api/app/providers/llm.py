"""The language model: one OpenAI-compatible implementation covers OpenRouter (the default),
OpenAI itself, and local servers such as llama.cpp's and Ollama's — only the base URL, key and
model differ, and those are config.

`chat()` returns the whole reply; `stream()` yields it as it is generated, which is what lets
MAYA start speaking after the first sentence instead of after the last.
"""

from __future__ import annotations

import json
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
class Done:
    finish_reason: str | None = None


LLMEvent = TextDelta | ToolCall | Done

# Generating a long reply can take a while; the read timeout is per chunk when streaming.
CHAT_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)


class LLMProvider(ABC):
    model_id: str

    @abstractmethod
    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """The whole reply, as an OpenAI-style message: {role, content, tool_calls?}."""

    @abstractmethod
    def stream(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> AsyncIterator[LLMEvent]:
        """TextDelta pieces as they're generated, then any ToolCalls (whole), then Done."""


class OpenAICompatibleLLM(LLMProvider):
    def __init__(self, base_url: str, model: str, api_key: str | None = None, *, name: str = "llm",
                 client: httpx.AsyncClient | None = None):
        self.base_url, self.model_id, self._api_key, self.name = base_url, model, api_key, name
        self._client = client

    def _http(self) -> httpx.AsyncClient:
        return self._client or client_for(self.base_url)

    def _build(self, messages, tools, stream: bool):
        body: dict[str, Any] = {"model": self.model_id, "messages": messages}
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

    async def chat(self, messages, tools=None):
        response = await send(self._http(), self._build(messages, tools, stream=False), provider=self.name)
        try:
            return response.json()["choices"][0]["message"]
        except (ValueError, KeyError, IndexError) as e:
            raise ProviderError(self.name, f"unexpected reply: {response.text[:200]}") from e

    async def stream(self, messages, tools=None):
        response = await send(self._http(), self._build(messages, tools, stream=True), provider=self.name,
                              stream=True)
        calls: dict[int, dict[str, str]] = {}
        finish_reason = None
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
        yield Done(finish_reason)
