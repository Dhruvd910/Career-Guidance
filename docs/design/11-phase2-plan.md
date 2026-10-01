# 11 — Phase 2 plan: Memory

Scope (spec §6–9, §21–22): structured student profile, counselling memory (threads + session
summaries), episodic timeline, semantic memory with relevance-based retrieval, "where we left
off", and the student-state model — on PostgreSQL + pgvector, with embeddings computed on the Pi,
behind consent. Design: doc 03; schema: doc 02 §2–5.

Decisions (2026-10-01): PostgreSQL 17 + pgvector on this Pi; embeddings on the Pi
(multilingual-e5-small, int8 ONNX, 384-dim); real students soon, so guardian consent is built
now — recorded as *declared*, not verified (DPDP's verifiable parental consent needs legal
advice and probably an identity service; flagged, not solved here).

## Refinements to doc 03, for latency

| Doc 03 said | Phase 2 does | Why |
|---|---|---|
| An LLM intent classifier picks a retrieval plan per turn | Retrieval = an always-on core (profile, open threads, current counselling state, last summary) + embedding top-k over memory items (~30 ms on the Pi) | An extra LLM call before every reply would undo Phase 1's latency win |
| State analyzer per turn | Runs **in parallel** with the reply; its result shapes the *next* reply and the session summary | Same reason; a feeling expressed now is still true one turn later |
| Session end | Explicit end, leaving MAYA's page, or **10 min idle** → summary + memory written in the background | A WebSocket can stay open all day; students never say "end session" |

## Steps

### Step 0 — PostgreSQL on the Pi
- `apt install postgresql-17 postgresql-17-pgvector`; local role + database `maya`, password in
  `apps/api/.env`; listen on localhost only.
- `psycopg[binary]` + `pgvector` in the API; `alembic upgrade head` on Postgres; a one-off copy
  script SQLite → Postgres (everything, sequences reset), verified by row counts.
- Tests stay on in-memory SQLite (fast); a `postgres` marker runs the vector-search tests
  against a throwaway Postgres database when it's available. An `Embedding` column type is
  pgvector on Postgres and JSON on SQLite; `VectorStore` searches with pgvector's `<=>` on
  Postgres and in Python elsewhere.

### Step 1 — Schema (one migration)
`student_profiles` += education_stage, stream, birth_year, city, study_hours_per_week ·
`student_interests`, `student_goals`, `student_constraints` · `consents`, `data_requests` ·
`counselling_threads`, `session_summaries`, `student_events`, `memory_items` (embedding) ·
`turn_analyses`.

### Step 2 — Embeddings on the Pi
`EmbeddingProvider` + `LocalE5Embedding` (ONNX Runtime + `tokenizers`, `query:`/`passage:`
prefixes, mean pooling, L2-normalised). Model downloaded to `apps/api/models/` (gitignored),
like the Vosk and Silero models. Check: Hindi/Hinglish/English paraphrases land closer than
unrelated sentences; ≤ 60 ms per sentence on the Pi.

### Step 3 — Consent
- Kinds: `long_term_memory`, `emotion_signals`, `guardian` (doc 02 §2). Default: **off**.
- Students under 18 (birth year, or class ≤ 12 without one) need a guardian's declared consent:
  guardian name, relationship, contact, a plain-language notice in English and Hindi, a
  timestamp and the notice version. Stored as `verification: "declared"`.
- Without consent MAYA still works — within one session only — and says so once.
- `GET/POST /api/consent`; withdrawing deletes the memory it covered (via `data_requests`).

### Step 4 — Writing memory (session end, background)
Transcript → one LLM call with a JSON schema → summary, decisions, open questions, next steps,
thread updates, interests/goals/constraints, events, memory items → validate (every item cites
messages; quotes must appear in them) → reconcile (near-duplicates update, contradictions
supersede) → one transaction. Sensitive items (family conflict, finances, health) flagged and
kept out of retrieval unless the question needs them.

### Step 5 — Reading memory (every turn, no added wait)
Context pack added to the prompt: profile snapshot, current counselling state, open threads,
last session summary, top-k memories by meaning, recent timeline — within a token budget, each
item tagged with its id. The state analyzer's signals from the previous turn adjust tone.

### Step 6 — "Where we left off"
On connect, if the last session was > 6 h ago and a thread is open, the server sends
`session.opening` (a short recap and check-in, generated from the state alone); MAYA says it
when she's woken, instead of "Yes? How can I help?".

### Step 7 — Student state (spec §5)
Parallel cheap LLM call per student turn → intent, topic, conversational signals (confusion,
pressure, comparison, low confidence…) with confidences, underlying concerns. Never clinical
terms, never on the profile, never shown to parents; < 0.5 confidence ignored. Separately, a
conservative check for self-harm or abuse disclosures switches MAYA to a supportive reply with
Tele-MANAS (14416) and a trusted adult.

### Step 8 — APIs and screens
APIs: `/api/student/memory` (list, delete), `/api/student/timeline`,
`/api/counselling/current-state|history|threads`, `/api/consent`. Desktop (800×480): consent
screen (guardian), **My memory** (see, delete), **My journey** (timeline).

### Step 9 — Phase 2 verification
Automated: writer validation (made-up quotes rejected), reconciliation, retrieval relevance,
consent gating (nothing written without consent), deletion really deletes (rows and vectors),
one student never sees another's memory. Hands-on: a script across two or three sittings on
different days ("talk about PCM vs PCB, stop; come back tomorrow").
