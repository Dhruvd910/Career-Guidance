# 10 — Phase 1 plan: Voice Mentor

Scope (spec §34): voice input, STT, LLM, TTS, Hindi/English/Hinglish, conversation
context, interruptions. **Not** in Phase 1: memory across sessions, emotion analysis,
assessment changes, graph, roadmap, college ingestion, Postgres.

Each step ends with its tests green and a commit. Steps 1–3 are server-only and fully
testable headless; steps 4–5 need the mic and speaker connected.

## Step 0 — Baseline & hygiene

| Task | Detail |
|---|---|
| Remove the Cartesia key from `.env.example` | User rotates the key at play.cartesia.ai and puts the new one only in `apps/api/.env` |
| Recreate both virtualenvs on this Pi | Current ones point at `/home/pi1/…`; `start.sh` can't run |
| `sudo apt install libportaudio2` | Unblocks desktop tests and audio |
| Plug in the USB sound card / mic | `arecord -l` currently shows no capture device |
| First git commit of the baseline | So Phase 1 is a reviewable diff |
| Record baseline | API tests (82 pass today), desktop tests, and a hand-timed voice turn as the "before" latency |

## Step 1 — Provider layer v2 (`apps/api/app/providers/`)

- `llm.py`: `LLMProvider` with `complete()` and `stream()` (SSE parsing incl. streamed tool
  calls); `OpenAICompatibleLLM(base_url, api_key, model)` covers OpenRouter today and
  OpenAI / llama.cpp server / Ollama by config.
- `stt.py`: Groq Whisper returning `Transcript(text, language, confidence, duration_ms)`;
  keeps today's "re-ask with language pinned to get Devanagari" behaviour.
- `tts.py`: Cartesia `stream()` returning raw PCM s16le chunks; `synthesize()` kept for the
  existing `/api/ai/speak` (desktop setup screens use it).
- `registry.py`: `LLM_PROVIDER`, `STT_PROVIDER`, `TTS_PROVIDER` config → instances;
  missing key → `None` (existing graceful-degradation behaviour preserved).
- Resilience: connect 5 s / first-token 20 s / total 60 s timeouts; jittered retries on
  429/5xx before first byte only; per-provider circuit breaker.
- `app/ai/providers.py` callers move to the registry; file removed.

Tests: `tests/fakes/` (scripted fake LLM that streams deltas/tool calls, fake STT/TTS);
SSE parsing incl. tool-call fragments; timeout and retry paths with `httpx.MockTransport`;
registry selection.

## Step 2 — Language intelligence (`apps/api/app/ai/language.py`)

- `detect()` → `LanguageTag{lang, script, confidence}` as doc 08 §3 (Roman-Hindi lexicon,
  mixed-script rule, Whisper tie-break, recent-language EMA for one-word replies).
- Reply instructions for `en`, `hi`, `hinglish`; `student_profiles.language_stats` updated per turn.
- **Spike S1** (≤ half a day, needs `CARTESIA_API_KEY`): synthesize the same Hinglish reply
  as Devanagari-mixed vs Roman; listen; pick the reply-script policy. Record the decision in doc 08.

Tests: a labelled set of ≥ 60 utterances (the spec's examples, today's
`tests/test_language.py` cases, Roman/Devanagari/mixed, short replies) with ≥ 95 % accuracy;
language switch mid-conversation keeps history and changes only the reply language.

## Step 3 — Streaming turn pipeline (server) (`apps/api/app/conversation/`)

- `chunker.py`: `SentenceChunker` (doc 08 §4 rules).
- `turn_runner.py`: STT → language → `orchestrator.stream` → chunker → ordered TTS worker
  (≤ 2 in flight) → events; cancellation via task cancel; persists `generated_content`,
  `content` (spoken part), `interrupted`, `latency`.
- `orchestrator.py` gains `stream()`; the tool loop is shared with the existing
  `handle_chat()` so `/api/ai/chat` and `/api/ai/voice-chat` keep working unchanged.
- Session context: token-budgeted history (~2 500 tokens) of the current session;
  interrupted turns annotated for the model.
- `routers/conversation.py`: `POST /conversation/start|message|end` (P1 versions: no memory),
  `WS /api/ws/conversation` (doc 07 §2).
- ~~`devices` table + pairing~~ deferred (D9: loopback-only API); the WS requires the student token.
- Migration: additive columns on `conversations`, `messages`.
- Structured JSON logging with `request_id`/`session_id`/`turn_id`.

Tests: chunker edge cases (₹1,20,000, B.Tech, "।", URLs, very long sentences); integration
over the WS with fake providers: event order, audio seq ordering, interrupt during LLM /
during TTS / between sentences → `turn.cancelled`, nothing after it, stored `content` equals
exactly what was played; new turn implicitly cancels the old; auth rejection (no token,
wrong device key, another student's session); provider failure → error frame + text-only.

## Step 4 — Edge voice client (`apps/desktop/app/`)

- `conversation_client.py`: WebSocket client on a worker thread, Qt signals per event,
  reconnect with backoff.
- `audio_io.py`: streaming PCM playback queue with per-chunk position tracking (for
  `playback.ack` / `played_ms_in_seq`); 300 ms pre-roll ring buffer on the mic.
- `vad.py`: `VoiceActivityDetector` interface; `SileroVAD` (onnxruntime) and the existing
  RMS detector as fallback; end-silence 0.7 s.
- `pages/maya.py` + `voice.py`: move MAYA's conversation onto the client; setup/onboarding
  screens keep using `/ai/speak` + `/ai/transcribe` (unchanged).
- Cached filler / error phrases per language, synthesised once and stored on the edge.

Tests (offscreen Qt, no hardware): client state machine against a fake server; playback
position maths; VAD on the existing synthetic audio fixtures plus recorded clips;
existing `test_voice_controller.py` updated, not deleted.

## Step 5 — Barge-in

- **Spike S2** (hardware required): run WebRTC-AEC and SpeexDSP Python bindings on the Pi 5
  with the real mic + speaker; for each, measure residual echo and VAD false-trigger rate
  while MAYA speaks 20 varied sentences at normal volume, and true-trigger rate for a person
  interrupting 20 times. Pass = 0 self-triggers and ≥ 18/20 true triggers. If neither passes,
  recommend a USB speakerphone with hardware AEC and use `wake_phrase` mode until then.
- `barge_in.py`: modes `aec_vad` | `hardware_aec` | `wake_phrase`, self-trigger guard and
  auto-fallback (doc 08 §5); local playback stop on trigger, then `turn.interrupt`.

Tests: guard logic (echo transcript vs spoken text), mode fallback, stop-then-notify ordering,
replay of recorded "speaker + interruption" clips through the detector.

## Step 6 — Phase 1 verification

Automated: all API + desktop suites green; WS protocol replay test pinned.

Hardware test script (`docs/design/phase1-test-script.md`, written in Step 5), run on the Pi
with a real person, results recorded in the repo:

| Check | Pass criterion |
|---|---|
| 20 turns mixed en / hi / Hinglish incl. the spec §32 examples | reply language matches in ≥ 19/20 |
| Mid-conversation language switch | next reply in the new language, context kept |
| Latency, end of speech → first audio | p50 ≤ 3 s, p90 ≤ 4.5 s (measured from logs) |
| Barge-in during speech, 20 trials | playback stops ≤ 300 ms after trigger in all; ≥ 18 recognised |
| Self-interruption while MAYA speaks for 5 minutes | 0 |
| Interrupted turn | next reply doesn't assume the unheard part was heard |
| TTS key removed | MAYA still works in text, says so once |
| Network cut mid-turn | edge reconnects; MAYA says the turn was lost |

## Risks

| Risk | Mitigation |
|---|---|
| Software AEC not good enough on this mic/speaker | S2 decides early; hardware speakerphone or wake-phrase fallback |
| Cartesia reads Roman Hinglish badly | S1; Devanagari-mixed replies |
| OpenRouter model streams tool calls inconsistently | provider contract tests per model; model is config |
| Cloud latency from India varies | measure per-stage; stage targets tell us which provider to swap |
| Pi CPU: Vosk + Silero + Qt GIFs together | measure; mascots already scaled to 480 px (15 % of a core) |
