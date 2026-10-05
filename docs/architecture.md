> **Superseded (2026-10-05).** This is the original architecture plan from before the phased build. The current design is in [`docs/design/`](design/00-README.md) — start with its README; the API is in [07-api-contracts](design/07-api-contracts.md) and FastAPI's own `/docs`.

# Architecture

Status: Phase 1 + MVP (see the master spec's own §53 phasing). This document describes
what's actually built, what's deliberately deferred, and why.

## 1. Frontend architecture

**Primary frontend: MAYA, a PySide6 (Qt) desktop app** — `apps/desktop/`. The product
direction shifted mid-build from a browser app to a named voice-assistant desktop
application with an animated mascot (Idle/Listening/Thinking/Talking states via `QMovie`
GIF playback), launched full-screen via `~/.xinitrc` → `run_kiosk.sh` on boot. It talks
to the exact same FastAPI backend as the web app below — no backend changes were needed
for the pivot, only a new client.

- `app/api_client.py` is a synchronous `httpx`-based mirror of the web app's `lib/api.ts`,
  one method per endpoint. `app/workers.py` runs every call on a `QThreadPool` worker so
  the UI thread never blocks; results/errors come back as Qt signals.
- `app/session.py` holds the JWT in `QSettings` (Qt's equivalent of `localStorage`) and
  exposes `logged_in`/`logged_out` signals that `MainWindow` uses to route between pages.
- `app/main_window.py` is a `QStackedWidget`-based router — `ctx.navigate(name, **kwargs)`
  swaps the visible page and calls its `on_show(**kwargs)` to refresh data. Every page in
  `app/pages/` subclasses `BasePage` for this contract.
- `app/pages/maya.py` is the assistant screen: mic input via `sounddevice` (records to
  WAV, sent to `/api/ai/voice-chat`), playback via `QtMultimedia` (`QMediaPlayer` +
  `QAudioOutput`, FFmpeg backend), and a new `POST /api/ai/speak` backend endpoint (added
  during this pivot) so typed replies get spoken too, not just voice-initiated ones.
- Verification note: this was built on a headless Pi with no display, no microphone, and
  no reachable audio session. Every page was verified by constructing the real
  `MainWindow` under Qt's offscreen platform and driving it programmatically (login,
  onboarding, every nav target, a live AI chat round-trip) — genuine functional coverage,
  but not the same as watching it render, hearing it speak, or recording a real voice
  clip. Worth a visual/audio pass on a machine with a screen and a mic.

**Earlier iteration, kept but no longer the active frontend: Next.js 16** (App Router,
Turbopack, React 19), TypeScript, Tailwind CSS v4, in `apps/web/`. Left in place rather
than deleted since it's a fully working, tested surface against the same backend.

- Almost every page is a Client Component. The app is an authenticated, per-student
  dashboard (not content/SEO-driven), and auth is a Bearer JWT held in `localStorage`
  (`apps/web/src/lib/api.ts`), which only exists in the browser — so server-rendered data
  fetching would not have access to it anyway. Pages fetch on mount via the typed client
  in `lib/api.ts`.
- The one exception forced by the framework: `app/colleges/[id]/page.tsx` is an async
  Server Component only because Next.js 16 requires `params` to be awaited there; it
  immediately hands off to `CollegeDetailClient.tsx` for everything else.
- `lib/auth-context.tsx` holds the current student profile in React context, refetched
  on mount from `GET /api/student/profile` using the stored token, and exposes
  `login`/`register`/`logout`. `components/ProtectedRoute.tsx` redirects to `/login` when
  unauthenticated.
- `components/ui.tsx` holds small shared primitives (Card/Button/Input/Select/Spinner/
  RangeSlider/Disclaimer/ErrorMessage) so pages stay short. `ChanceBadge.tsx` and
  `Provenance.tsx` render the 🟢/🟡/🔴 chance badges and the "source + last verified"
  line that appears on every factual figure, per the spec's source-transparency
  requirement (§43).
- Theme tokens (including the chance-band colors) live in `app/globals.css` using
  Tailwind v4's CSS-first `@theme` block — light/dark both defined, no `tailwind.config.js`.

## 2. Backend architecture

FastAPI, layered as `routers/` (thin HTTP layer) → `services/` (business logic,
framework-agnostic) → `models/` (SQLAlchemy ORM) / `schemas/` (Pydantic I/O contracts).

- `core/config.py` — typed settings from `.env` (pydantic-settings).
- `core/db.py` — SQLAlchemy engine/session; SQLite today, swappable to PostgreSQL via
  `DATABASE_URL` alone since no SQLite-only column types are used.
- `core/security.py` / `core/deps.py` — bcrypt password hashing, JWT issuance/decoding,
  and the `get_current_user` / `get_current_student_profile` FastAPI dependencies.
- Every router follows the same shape: validate via a Pydantic schema, delegate to a
  service function, return a schema. Routers never touch SQLAlchemy models directly for
  business logic, so the same services back both the REST API and the AI tool layer
  (`app/ai/tools.py`) — the LLM and the frontend hit identical, identically-validated code
  paths.

## 3. Database architecture

See `apps/api/app/models/` (one file per entity family) and the single Alembic migration
in `apps/api/alembic/versions/`. Every factual (non-user-generated) table mixes in
`ProvenanceMixin` (`source`, `source_url`, `academic_year`, `last_verified`,
`verification_status`) — this is what powers the "DEMO DATA" banners and source lines in
the UI, and what an eventual ingestion pipeline would need to populate honestly instead
of leaving as `unverified_demo`.

The spec's §22 wishlist of ~30 tables is intentionally trimmed for this phase.
`college_courses` carries `(college, course, branch, exam)`; `cutoffs` hangs off
`college_courses` and adds `(year, round, category, quota, seat_type)` — this is what
makes predictions branch-level and quota-aware (§10) instead of "you can get college X."
Not yet split into their own tables (folded into JSON columns or simply not modeled yet):
`universities` (colleges cover this for now), `counselling_authorities` /
`counselling_rounds` (the `round`/`quota` columns on `cutoffs` cover the common case),
`seat_matrices` (covered by `college_courses.total_seats`), `data_sources` /
`data_updates` (each table's own provenance columns cover this until a shared source
registry is actually needed), and `subjects` (marks are a JSON column on
`academic_records` until a real curriculum catalog is needed).

## 4. AI architecture

`apps/api/app/ai/`:

- `providers.py` — `LLMProvider` / `STTProvider` / `TTSProvider` abstract interfaces,
  each with one concrete implementation (OpenRouter / Groq / Cartesia respectively, all
  OpenAI-compatible or plain REST). Swapping providers means adding a new subclass and
  changing `get_llm_provider()` (etc.) — nothing else in the app changes. If a key is
  missing, the getter returns `None` and callers degrade gracefully rather than crashing.
- `tools.py` — the function-calling surface (`TOOL_SPECS` JSON schemas +
  `execute_tool()` dispatcher). Every tool is a direct call into the same `services/`
  functions the REST API uses — the model cannot fabricate a fee, cutoff, or placement
  number because it never generates them; it can only relay what a tool call returned.
- `orchestrator.py` — the chat loop: builds the system prompt (encodes the "never
  guarantee admission," "cite verification status," "category is never an ability
  signal" rules from spec §42/§61), runs the tool-calling loop against the configured
  LLM, and persists `Conversation`/`Message` rows.
- `summarize.py` — a separate, simpler one-shot LLM call (no tool loop) used only for the
  college-comparison narrative (§20); it's handed the already-computed comparison table
  as its entire context and is explicitly instructed not to add outside facts.

Voice: `POST /api/ai/voice-chat` transcribes via Groq, runs the transcript through the
same `handle_chat` pipeline as text, then optionally synthesizes the reply via Cartesia
and returns both text and base64 audio. All three providers are cloud APIs — deliberate,
since this backend may run on modest hardware with no room for local model inference.
`POST /api/ai/speak` (added for the desktop pivot) synthesizes arbitrary reply text on
its own, decoupled from the chat pipeline — MAYA calls it after a text-only `/chat` reply
so she speaks regardless of whether the student typed or talked. Both speech paths cap
input at ~500 characters and swallow TTS provider errors (e.g. exhausted Cartesia
credits) into a silent `None` rather than failing the request — text always still works.

## 5. Prediction / ML architecture

`services/prediction_service.py` — deliberately a transparent rule-based baseline, not a
trained model, per spec §27's explicit instruction to start there. For a given exam,
rank, and category, it gathers historical closing ranks per
`(college, branch, quota)`, and classifies against the ratio of the student's rank to the
**median** closing rank across all seeded years:

| ratio (rank / median closing rank) | band |
|---|---|
| ≤ 0.85 | 🟢 High Probability |
| 0.85–1.05 | 🟡 Possible |
| 1.05–1.30 | 🔴 Ambitious/Dream |
| \> 1.30 | not shown (false hope, not "ambitious") |

Every result carries the actual per-year closing ranks used and how many years/rounds
were considered (`PredictionExplanation`), so nothing is an unexplained score (§28). The
counselling preference-list generator (§21) reuses the exact same historical-stats
gathering function with a finer 5-label scale (Safe/Good Chance/Possible/Ambitious/Dream).

This is intentionally swappable: a future `MLPredictionEngine` (XGBoost/LightGBM per
§27) can implement the same input/output contract and replace the ratio-based
classification without any router, AI-tool, or frontend change.

## 6. Data ingestion — designed for, not built

No PDF/OCR ingestion pipeline exists yet (that's explicitly Phase 5 in the master spec).
What's in place so it can be added without a redesign:
- Every factual table already has the provenance columns an ingestion pipeline would
  populate.
- `apps/api/app/seed/seed.py` is the interim "ingestion" — a script that loads data into
  the same models a real pipeline would target, with `verification_status =
  "unverified_demo"`. A real pipeline would produce the same rows with real sources and
  `verification_status = "verified"`.
- College identity is already keyed by canonical `College` rows with an `aliases` JSON
  column (spec §26 normalization), so a name-matching step in a future ingestion job has
  somewhere to write matches without inventing new schema.

## 7. What's explicitly out of scope for this phase

- **Admin panel UI** — the service layer already has everything an admin UI would call
  (college/cutoff/fee CRUD is just normal SQLAlchemy sessions); only the UI is missing.
- **RAG/embeddings/pgvector** — no document knowledge base yet; the AI only ever answers
  from the structured database via tool calls.
- **Real ML models (XGBoost/LightGBM)** — see §5 above; the `PredictionEngine` contract
  is ready for one to be swapped in.
- **Redis/Celery background jobs** — nothing in this phase needs a job queue (no PDF
  ingestion pipeline yet to schedule).
- **Notifications, monetization, parent/counsellor accounts** — `users.role` already
  supports adding `parent`/`counsellor` later without a schema change.
- **Live maps/places integration** — `nearby_places` has real schema and seeded sample
  rows; wiring a live provider (Google Places, Mapbox, etc.) needs its own API-key
  decision first.
- **PostgreSQL migration** — the models avoid SQLite-only types specifically so this is a
  `DATABASE_URL` change plus a fresh `alembic upgrade head`, not a rewrite.
