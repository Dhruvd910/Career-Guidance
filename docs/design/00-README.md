# Design: AI Career Counsellor & Personal Career Mentor

Status (2026-10-02): **Phases 1-5 built** (voice mentor; memory; assessment; career engine; roadmap)
and awaiting their hands-on tests; Phases 6-7 designed, not built. Written against the code in `apps/` (MAYA).

| # | Document | Answers |
|---|---|---|
| 01 | [System architecture](01-system-architecture.md) | Modules, service interfaces, edge vs server, deployment |
| 02 | [Database / ER schema](02-database-schema.md) | Every table, which phase adds it, what changes in existing tables |
| 03 | [Memory schema](03-memory-schema.md) | Memory layers, write path, retrieval, "where we left off", privacy |
| 04 | [Knowledge graph](04-knowledge-graph.md) | Node/edge types, storage, queries |
| 05 | [RAG pipeline](05-rag-pipeline.md) | Ingestion, chunking, embeddings, hybrid retrieval, what RAG must *not* answer |
| 06 | [College data & provenance](06-college-provenance.md) | Facts model, source tiers, freshness, conflicts |
| 07 | [API contracts](07-api-contracts.md) | REST + the voice WebSocket protocol |
| 08 | [Voice pipeline](08-voice-pipeline.md) | VAD, STT, language, streaming, barge-in, latency budget |
| 09 | [Roadmap data model](09-roadmap-model.md) | Class-aware templates, versioning, adaptation rules, progress |
| 10 | [Phase 1 plan](10-phase1-plan.md) | Concrete steps, files, tests, exit criteria |
| 11 | [Phase 2 plan](11-phase2-plan.md) | Memory: PostgreSQL, on-device embeddings, consent, writing and reading memory |
| 12 | [Phase 3 plan](12-phase3-plan.md) | Assessment: interest, aptitude, skills, academic profile, career directions, reassessment |
| 13 | [Phase 4 plan](13-phase4-plan.md) | Career engine: knowledge graph, pathways, skill paths, stream choices, colleges from official data |
| 14 | [Phase 5 plan](14-phase5-plan.md) | Roadmap: class-aware and personal, versioned, adapting to time / difficulty / interest changes; progress |
| — | [Phase 1 test](phase1-test-script.md) · [Phase 2 test](phase2-test-script.md) · [Phase 3 test](phase3-test-script.md) · [Phase 4 test](phase4-test-script.md) · [Phase 5 test](phase5-test-script.md) | Hands-on checks with a person |

---

## 1. Starting point: what MAYA already has vs. what the spec needs

This is not a greenfield project. MAYA already covers a large part of Phase 1 and pieces
of Phases 3–6. The design **evolves the existing codebase** rather than rewriting it.

| Spec area | Exists today | Gap |
|---|---|---|
| Voice in/out | Groq Whisper STT, Cartesia TTS, RMS-energy VAD, Vosk wake word on the Pi | Whole-reply-then-speak (5–9 s silence per turn); no streaming |
| Hindi / English | Whisper language + Devanagari-ratio detection; reply-language instruction | **Hinglish in Roman script is classified as English** ("Mujhe samajh nahi aa raha" → English reply) |
| Barge-in | Only by saying "Stop Maya"/"Hey Maya" (wake phrase) | No interruption by simply speaking; needs echo cancellation |
| Conversation context | Last 20 messages of one conversation | No cross-session memory at all |
| LLM abstraction | `LLMProvider`/`STTProvider`/`TTSProvider` ABCs, one impl each | No streaming, no timeouts/retries policy, no embedding/vector/graph abstractions |
| Student profile | `student_profiles`, `academic_records` | No interests/skills/goals/constraints, no education stage beyond class 8–12 |
| Assessment | ~30-question conversational career assessment, scored per career | Single instrument; no aptitude/skill measurement; no re-assessment history |
| Careers | `career_options` with JSON relations + rich `details` | Relations are JSON id lists, not a queryable graph |
| Roadmap | Deterministic template by class + exam, NCERT study plan | Not versioned, not personalised beyond class/exam, no progress |
| Colleges | **Real** JoSAA 2026 + MCC 2026 cutoffs, 28 researched profiles with sources, `ProvenanceMixin` | Provenance is per-row, not per-field; no freshness policy; `seed.py` can still load demo colleges (this DB has none: 739 colleges, all official); fees/hostel/facility tables are empty — facts exist only for the 28 researched colleges |
| Safety | Strong system-prompt rules; facts only via tool calls | No emotion handling, no escalation path |

## 2. Key decisions

| ID | Decision | Why |
|---|---|---|
| D1 | **Evolve MAYA**, keep FastAPI + SQLAlchemy + Alembic + PySide6 | ~70% of Phase 1 exists and is tested; the layering (routers → services → models) already matches the spec's "separate but connected modules" |
| D2 | **Modular monolith**: one API process, strict module interfaces | One Pi, one team. Interfaces (doc 01) make splitting into services later a deployment change, not a rewrite |
| D3 | **PostgreSQL 16 + pgvector** as the single store from Phase 2; SQLite stays for Phase 1 | Memory (Phase 2) needs vector search and JSONB. One database is the "simplest architecture" the spec asks for. Runs fine on a Pi 5 (8 GB) |
| D4 | **No Neo4j.** Graph = `kg_nodes`/`kg_edges` tables behind a `GraphStore` interface, queried with recursive CTEs | The graph is small (10³–10⁴ nodes). A graph DB would be a second system to run on the Pi for no query we can't already express |
| D5 | **Streaming turns over a WebSocket** between the Pi app and the API | Needed for sentence-by-sentence speech (latency) and for interrupt signalling (barge-in) |
| D6 | **Cloud providers by default, every one swappable**; the LLM provider is "OpenAI-compatible" so OpenRouter, OpenAI, llama.cpp server and Ollama are config changes | Spec §27; keeps a local-only path open |
| D7 | **Time-sensitive numbers reach the LLM only from the `facts` table, with provenance attached.** RAG text never answers a fee/date/cutoff | Spec §13–16; the LLM can't fabricate what it only relays |
| D8 | **Demo data leaves the production database.** Fixtures move to `tests/fixtures/`; the app refuses to start in `production` if any fixture-origin row exists | Spec §35 |
| D9 | **Everything runs on this Raspberry Pi 5** (decided 2026-10-01): desktop app, API, and PostgreSQL from Phase 2. Only the LLM, STT and TTS are cloud services | One device, no multi-device sharing yet. The API stays a separate process (responsive UI, independent restarts, headless tests), and moving it to its own machine later is a config change (`API_BASE_URL`) |

## 3. Issues found while reviewing

Step 0 status as of 2026-10-01:

1. **A live Cartesia API key was in `.env.example`** (the shareable template), and that file
   travelled on a pendrive. *Done:* removed from the template (the same key is still in the
   gitignored `apps/api/.env`). *Open:* rotate it at play.cartesia.ai.
2. **Cartesia returns `402 Payment Required`** — its credits are used up, so MAYA currently
   has no voice (text still works). *Open:* top up or use a new account. OpenRouter (key
   valid, no spend limit set) and Groq (key valid) are fine.
3. *Done:* **both virtualenvs rebuilt** on this Pi (the copies pointed at `/home/pi1/...`).
4. *Done:* PortAudio present; the USB mic (`USB PnP Sound Device`, card 2) is detected.
5. *Done:* **tests green** — API 82/82, desktop 249/249. Five desktop VAD tests had been
   failing because the test's fake microphone didn't accept the `device` argument the code
   now passes; the fake was updated, the code under test was not changed.
6. *Open:* **Git has no commits.** Commit the baseline before Phase 1 so every phase is a reviewable diff.
7. **Students are mostly minors.** India's DPDP Act 2023 requires verifiable parental
   consent for processing children's personal data and restricts behavioural monitoring of
   children. Long-term memory and emotion signals are exactly that kind of processing.
   The schema includes consent and deletion (doc 02/03), but **get legal review before any
   real student uses it.**

## 4. Target folder structure

New code follows the existing layering. Subsystems with real internal structure get a
package under `app/` the way `app/ai/` already does. `(P2)` = phase that introduces it.

```
career/
├── apps/
│   ├── api/                          # SERVER — FastAPI modular monolith
│   │   ├── alembic/versions/         # one migration per phase step
│   │   ├── app/
│   │   │   ├── core/                 # config, db, security, deps, logging (+ request ids), rate limit
│   │   │   ├── providers/            # (P1) replaces ai/providers.py
│   │   │   │   ├── llm.py            #   LLMProvider + OpenAICompatibleLLM (OpenRouter/OpenAI/llama.cpp/Ollama)
│   │   │   │   ├── stt.py            #   STTProvider + GroqWhisper
│   │   │   │   ├── tts.py            #   TTSProvider + Cartesia (streaming)
│   │   │   │   ├── embedding.py      #   (P2) EmbeddingProvider
│   │   │   │   ├── web.py            #   (P6) WebDataProvider (fetch with provenance)
│   │   │   │   └── registry.py       #   build providers from config
│   │   │   ├── ai/                   # orchestrator, prompts, tools, language, state analyzer (P2)
│   │   │   ├── conversation/         # (P1) streaming turn runner, sentence chunker, WS session
│   │   │   ├── memory/               # (P2) writer, retriever, context packer, session summariser
│   │   │   ├── assessment/           # (P3) instruments, scoring, alignment
│   │   │   ├── knowledge/            # (P4) graph store, (P6) facts, freshness, RAG ingest/retrieve
│   │   │   ├── roadmap/              # (P5) templates, generator, adaptation rules, diff
│   │   │   ├── models/  schemas/  routers/  services/   # existing layering, extended per phase
│   │   │   └── seed/                 # reference data only (exams, syllabus, official cutoffs)
│   │   ├── ingest/                   # (P6) offline ingestion jobs: fetch → extract → validate → load
│   │   └── tests/
│   │       ├── fixtures/             # clearly-labelled mock data (incl. today's demo colleges)
│   │       ├── unit/  integration/
│   │       └── fakes/                # fake LLM/STT/TTS/embedding providers
│   ├── desktop/                      # EDGE — PySide6 app on the Pi (mic, VAD, playback, UI)
│   │   └── app/
│   │       ├── conversation_client.py  # (P1) WebSocket client
│   │       ├── vad.py                  # (P1) Silero VAD + existing RMS fallback
│   │       ├── barge_in.py             # (P1) AEC+VAD / wake-phrase / off
│   │       └── pages/                  # + journey, timeline, progress, roadmap tree (P2–P5)
│   └── web/                          # earlier Next.js client, unchanged
└── docs/design/                      # this folder
```
