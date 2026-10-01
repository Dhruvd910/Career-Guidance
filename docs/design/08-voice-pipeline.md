# 08 — Voice pipeline (Phase 1)

## 1. Today vs. target

| Step | Today | Target |
|---|---|---|
| Capture | `sounddevice`, 44.1/48 kHz USB mic → 16 kHz | same |
| VAD | RMS energy with ambient calibration, 1.2 s end-silence | **Silero VAD** (ONNX, CPU) behind a `VoiceActivityDetector` interface; RMS kept as fallback; end-silence 0.7 s, adaptive (longer after a question that invites a long answer) |
| Wake | Vosk "Hey Maya", local | same |
| STT | Groq Whisper, whole utterance | same (utterances are short; batch is fine). Language hint from the student's recent turns |
| Language | en/hi by Devanagari ratio | **en / hi / hinglish** with script (§3) |
| LLM | full reply, then speak | **streamed**; sentence chunker |
| TTS | Cartesia, whole reply, mp3 | Cartesia **per sentence, raw PCM**, ≤2 sentences synthesised ahead |
| Playback | play whole clip | ordered chunk queue with position tracking |
| Barge-in | wake phrase only ("Stop Maya") | **just start talking** (AEC + VAD), wake phrase as fallback |

## 2. Edge state machine

```
           wake word / tap / auto-listen after a question
  IDLE ───────────────────────────────────────────────► LISTENING
   ▲                                                      │ VAD end-of-utterance
   │ reply.done & no follow-up                            ▼
   │                                                   THINKING ── turn.thinking (filler, mascot)
   │                                                      │ first reply.audio
   │            barge-in (speech during THINKING/SPEAKING)▼
   └──────────────────── SPEAKING ◄───────────────────────┘
                            │ barge-in detected
                            ▼
              stop playback (local, immediate) → send turn.interrupt
              → LISTENING (with 300 ms pre-roll so the first syllable isn't lost)
```
The mascot (Idle/Listen/Think/Talk GIFs) is driven only by this state.

## 3. Language intelligence

`detect(text, whisper_language) -> LanguageTag{lang: en|hi|hinglish, script: latn|deva, confidence}`

1. Script: share of Devanagari letters (existing `language_of_text` logic).
2. Roman-script Hindi: a lexicon of high-frequency Hindi function words and verbs written in
   Latin (`mujhe, mera, nahi, kya, hai, hoon, karna, chahiye, aur, lekin, kyunki, samajh,
   ho, raha, gaya…`, with spelling variants). Share of Hindi tokens among words:
   ≥ 0.6 → `hi`, 0.2–0.6 → `hinglish`, < 0.2 → `en`.
3. Devanagari text with ≥ 15 % Latin words (excluding acronyms like JEE/IIT) → `hinglish`.
4. Whisper's language is a tie-breaker for very short utterances; for one-word replies
   ("haan", "ok") the student's recent language (EMA in `language_stats`) decides.

**Reply policy**: mirror the current turn (spec §4). Hindi/Hinglish replies keep exam,
college and technical terms in English as students say them. The student's profile stores
the running mix, never a hard setting, so switching mid-conversation just works.

**Script for speech** — open question, settled by spike S1 in Phase 1: Cartesia's Hindi
voice is known to read Devanagari; how it reads Roman-script Hinglish is unverified. Options:
(a) LLM writes Hinglish replies in Devanagari with English terms in Latin (likely best for
TTS; screen shows the same text); (b) Roman for screen + transliterated Devanagari for TTS
(extra step). Default to (a) unless S1 shows Roman reads well.

## 4. Server streaming turn

```python
async def run_turn(session, turn):               # conversation/turn_runner.py
    transcript = await stt.transcribe(turn.audio, hint=session.language_hint)
    emit(turn.transcript)
    tag = language.detect(transcript.text, transcript.language)
    emit(turn.thinking)
    deltas = orchestrator.stream(session, transcript.text, tag)   # handles tool loops inside
    async for sentence in SentenceChunker(deltas):                # splits on . ? ! । and on
        emit(reply.delta(sentence))                               #   length > ~220 chars at a comma
        tts_queue.put(sentence)                                   # worker: ≤2 synth in flight, ordered emit
    emit(reply.done)
```
- **Chunker** rules: first chunk may be shorter (≥ 4 words) to cut time-to-first-audio;
  never split inside numbers ("₹1,20,000"), abbreviations ("B.Tech", "Dr."), or URLs; strips
  markdown (the policy prompt already asks for speakable text).
- **Tools** happen before any text in a typical turn. While a tool runs, the edge plays a
  short pre-synthesised filler in the current language ("Ek second, main dekh rahi hoon…" /
  "Let me check that…"), cached on the edge so it costs no API call.
- **Cancellation**: the turn is an `asyncio.Task`; `turn.interrupt` cancels it, which closes
  the LLM HTTP stream and pending TTS requests. The assistant message is saved with
  `content` = sentences fully played + the played fraction of the current one (from
  `played_ms_in_seq`), `generated_content` = everything generated, `interrupted = true`.
  The next prompt sees: *"(You were interrupted after saying: '…')"* so MAYA doesn't assume
  the student heard the rest.

## 5. Barge-in

The hard part is the speaker: the mic hears MAYA's own voice, and a naive VAD would
interrupt her with her own words. The design has three modes, chosen by config and by a
runtime self-check:

| Mode | How | When |
|---|---|---|
| `aec_vad` | Software echo cancellation using the exact PCM being played as the reference signal (WebRTC AEC3 or SpeexDSP binding — chosen in spike S2), then Silero VAD on the cleaned signal. Trigger = speech prob > 0.6 for ≥ 250 ms | Default if S2 passes |
| `hardware_aec` | USB speakerphone with built-in AEC; plain VAD | If software AEC isn't good enough on this hardware |
| `wake_phrase` | Existing Vosk "Stop Maya"/"Hey Maya" during speech | Fallback; always available |

**Self-trigger guard**: if a barge-in's transcript closely matches what MAYA was saying
(normalised token overlap > 0.7), it's counted as echo, discarded, and MAYA resumes; three in
a session → automatically drop to `wake_phrase` mode and log it.

**Stop latency**: playback is stopped **locally** the moment the trigger fires (no round
trip); the server is informed afterwards.

## 6. Latency budget (targets to measure, not promises)

From the student's last word to MAYA's first audio:

| Stage | Today (est.) | Target |
|---|---|---|
| End-of-utterance silence | 1 200 ms | 700 ms |
| Upload + STT (Groq) | 600–1 000 | 600–1 000 |
| LLM to first sentence | full reply 2–5 s | 700–1 500 |
| TTS first chunk | full reply 1–2 s | 250–500 |
| **Total p50** | **~5–9 s** | **≤ 3 s** (≤ 2.5 s without tool calls) |

Every turn logs these stages (`messages.latency`), so the target is checked on real turns.

## 7. Failure behaviour

| Failure | Behaviour |
|---|---|
| STT fails/times out | "Sorry, I didn't catch that" (cached audio), back to LISTENING |
| LLM timeout before any text | error frame; cached apology; turn not saved as assistant reply |
| TTS fails | text still shown; circuit breaker opens → text-only for 60 s, then retry |
| WebSocket drops | edge reconnects with backoff; current turn is lost and said so; session continues |
| No mic | touch/typing only (existing behaviour) |
