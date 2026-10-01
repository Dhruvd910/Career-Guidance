"""Every external AI service MAYA uses, behind an interface (spec §27).

The rest of the app talks to `LLMProvider`, `STTProvider` and `TTSProvider` — never to
OpenRouter, Groq or Cartesia directly — and gets them from `registry`, which builds whichever
implementation the config names. A missing key means "not configured" (None), never a crash.
"""
