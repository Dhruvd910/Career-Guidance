"""Stand-ins for the AI providers, so tests never call a paid service."""

from __future__ import annotations

from app.providers.llm import Done, LLMProvider, TextDelta, ToolCall
from app.providers.stt import STTProvider, Transcript
from app.providers.tts import TTSProvider


class FakeSTT(STTProvider):
    def __init__(self, text: str = "My name is Dhruv.", language: str = "en", **extra):
        self.result = Transcript(text=text, language=language, **extra)

    async def transcribe(self, audio_bytes, filename):
        return self.result


class FakeTTS(TTSProvider):
    """PCM of the right length for the text — 100 samples per character — so tests can tell
    which sentence a chunk belongs to by its size."""

    sample_rate = 16000

    def __init__(self, fail: Exception | None = None):
        self.fail = fail
        self.spoken: list[str] = []

    async def synthesize(self, text, language=None):
        if self.fail:
            raise self.fail
        self.spoken.append(text)
        return b"RIFFfake", "audio/wav"

    async def stream(self, text, language=None):
        if self.fail:
            raise self.fail
        self.spoken.append(text)
        pcm = b"\x01\x00" * 100 * len(text)
        for i in range(0, len(pcm), 4000):
            yield pcm[i:i + 4000]


class FakeLLM(LLMProvider):
    """Replies from a script: each turn is a reply text, or a list of (tool name, arguments)
    calls to make first. `seen` records the messages of every request."""

    model_id = "fake"

    def __init__(self, *turns):
        self.turns = list(turns)
        self.seen: list[list[dict]] = []

    def _next(self, messages):
        self.seen.append([dict(m) for m in messages])
        return self.turns.pop(0) if self.turns else "OK."

    async def chat(self, messages, tools=None):
        turn = self._next(messages)
        if isinstance(turn, list):
            return {"role": "assistant", "content": "", "tool_calls": [
                {"id": f"call_{i}", "type": "function", "function": {"name": name, "arguments": args}}
                for i, (name, args) in enumerate(turn)
            ]}
        return {"role": "assistant", "content": turn}

    async def stream(self, messages, tools=None):
        turn = self._next(messages)
        if isinstance(turn, list):
            for i, (name, args) in enumerate(turn):
                yield ToolCall(id=f"call_{i}", name=name, arguments=args)
        else:
            for word in turn.split(" "):  # piece by piece, the way a model streams
                yield TextDelta(word + " ")
        yield Done("stop")
