# 01 — System architecture

## 1. Shape

A **modular monolith**: one FastAPI process with strict module boundaries, plus an edge
app on the Pi. Modules talk only through the interfaces in §3 — never through each
other's tables — so any module can later become its own service.

```
 EDGE (Raspberry Pi 5, apps/desktop)                 SERVER (apps/api — same Pi or remote)
┌──────────────────────────────────┐                ┌─────────────────────────────────────────────────┐
│ Mic ─► AEC ─► VAD ─► utterance   │   WebSocket    │ Gateway: auth, rate limit, request ids          │
│        │       └─► barge-in ─────┼──interrupt───► │   │                                             │
│ Wake word (Vosk, local)          │◄──events/audio─┤ Conversation module (turn runner)               │
│ Playback queue ─► Speaker        │                │   │  STT ─► Language ─► Orchestrator ─► Chunker ─► TTS
│ UI: mascot states, pages, touch  │  REST (pages)  │   │                 │                           │
└──────────────────────────────────┘◄──────────────►│   │     ┌───────────┼───────────────┐           │
                                                    │   │     ▼           ▼               ▼           │
                                                    │   │  Memory     Student-state    Tools ──────┐  │
                                                    │   │  (P2)       analyzer (P2)                │  │
                                                    │   ▼                                          ▼  │
                                                    │ Student/Profile · Assessment · Career engine ·  │
                                                    │ Roadmap · Progress · College                    │
                                                    │   │                                             │
                                                    │ Knowledge layer: GraphStore · Facts · RAG       │
                                                    │   │                                             │
                                                    │ PostgreSQL + pgvector  (SQLite in Phase 1)      │
                                                    │ Ingestion jobs (offline) ◄── official sources   │
                                                    └─────────────────────────────────────────────────┘
                                                          │ cloud: LLM (OpenRouter) · STT (Groq) · TTS (Cartesia)
```

### Edge vs server (spec §28)

| Edge (Pi app) | Server (API) |
|---|---|
| Mic capture, resampling, echo cancellation | STT, language detection |
| VAD + end-of-utterance detection | LLM orchestration + tools |
| Barge-in detection, instant local playback stop | Memory, assessment, career, roadmap, college |
| Wake word (Vosk, offline — no room audio leaves the device until called) | Knowledge graph, facts, RAG |
| Streaming playback queue, mascot states, touch UI | Persistence, auth, observability |

The edge never holds student data beyond the auth token and on-screen state. The API URL is
config (`API_BASE_URL`), so the server can move off the Pi without touching the edge.

## 2. One conversational turn

```
edge: VAD end-of-utterance ──► send audio (turn_id)
server:
  1  STT (Groq Whisper) ─────────────────────────► transcript + language
  2  LanguageTag = detect(transcript, whisper_lang)                           (P1)
  3  StudentState = analyzer(transcript, recent turns)  — async, never blocks (P2)
  4  ContextPack = memory.retrieve(student, transcript, intent)               (P2)
  5  Orchestrator.stream(policy + snapshot + ContextPack + history + tools)
       ├─ tool calls → services (career/college/roadmap/...) → results with provenance
       └─ text deltas
  6  SentenceChunker: deltas ─► speakable sentences
  7  TTS per sentence (≤2 in flight) ─► audio chunks ─► edge plays in order
  8  persist turn: what was generated, what was actually spoken, latencies
edge: interrupt at any point ─► server cancels steps 5–7, stores spoken portion only
```

Session lifecycle (spec §22) wraps turns: `start` loads context and the "where we left
off" opening (P2); `end` runs the session summariser and memory writer (P2) as a background
job so the student never waits for it.

## 3. Service interfaces

Python `Protocol`s, one per module. Callers depend on these, never on implementations.
Types such as `LLMRequest` are Pydantic models in `app/schemas/`.

```python
# ---------- providers (app/providers) ----------
class LLMProvider(Protocol):
    model_id: str
    async def complete(self, req: LLMRequest) -> LLMResponse: ...
    def stream(self, req: LLMRequest) -> AsyncIterator[LLMEvent]: ...      # TextDelta | ToolCall | Done(usage)

class STTProvider(Protocol):
    async def transcribe(self, audio: AudioClip, hint: LanguageHint | None = None) -> Transcript: ...
    # Transcript: text, language, confidence, duration_ms

class TTSProvider(Protocol):
    def stream(self, text: str, voice: VoiceSpec) -> AsyncIterator[AudioChunk]: ...   # raw PCM s16le
    async def synthesize(self, text: str, voice: VoiceSpec) -> AudioClip | None: ...

class EmbeddingProvider(Protocol):                                           # (P2)
    model_id: str; dim: int
    async def embed(self, texts: list[str], kind: Literal["query", "passage"]) -> list[list[float]]: ...

class VectorStore(Protocol):                                                 # (P2) pgvector impl
    async def upsert(self, collection: str, items: list[VectorItem]) -> None: ...
    async def search(self, collection: str, vector: list[float], filters: dict, k: int) -> list[VectorHit]: ...

class GraphStore(Protocol):                                                  # (P4) Postgres impl
    def node(self, key: str) -> Node | None: ...
    def neighbors(self, key: str, edge_types: list[str], direction: Direction, depth: int = 1) -> list[Edge]: ...
    def paths(self, src: str, dst_type: str, via: list[str], max_depth: int) -> list[Path]: ...

class WebDataProvider(Protocol):                                             # (P6)
    async def fetch(self, url: str) -> FetchedDocument: ...                  # bytes, mime, retrieved_at, sha256, http status

# ---------- domain modules ----------
class ConversationService(Protocol):
    async def start(self, student_id: int, device_id: str | None) -> SessionStart: ...   # session id + opening line
    def run_turn(self, session_id: int, turn: UserTurn) -> AsyncIterator[TurnEvent]: ...
    async def interrupt(self, session_id: int, turn_id: str, played: PlaybackPosition) -> None: ...
    async def end(self, session_id: int) -> None: ...                         # schedules summary + memory write

class MemoryService(Protocol):                                               # (P2)
    async def session_context(self, student_id: int) -> SessionContext: ...  # profile snapshot, open threads, last summary
    async def retrieve(self, student_id: int, query: str, intent: Intent) -> ContextPack: ...
    async def write_session(self, session_id: int) -> SessionSummary: ...
    async def record_event(self, student_id: int, event: StudentEvent) -> None: ...

class StudentStateAnalyzer(Protocol):                                        # (P2)
    async def analyze(self, utterance: str, recent: list[Turn]) -> StudentState: ...

class AssessmentService(Protocol):                                           # (P3)
    def start(self, student_id: int, instrument_key: str) -> Attempt: ...
    def answer(self, attempt_id: int, item_key: str, answer: Answer) -> NextItem | AttemptComplete: ...
    def result(self, attempt_id: int) -> AssessmentResult: ...               # dimension scores + career alignments

class CareerEngine(Protocol):                                                # (P4)
    def options(self, student_id: int, limit: int = 6) -> list[CareerDirection]: ...  # with why/gaps/pathways
    def explain(self, student_id: int, career_key: str) -> CareerExplanation: ...

class RoadmapEngine(Protocol):                                               # (P5)
    def current(self, student_id: int) -> RoadmapVersion: ...
    def recalculate(self, student_id: int, trigger: RoadmapTrigger) -> RoadmapVersion: ...  # never mutates old versions
    def next_step(self, student_id: int) -> RoadmapNode | None: ...

class ProgressService(Protocol):                                             # (P5)
    def record(self, student_id: int, measurement: SkillMeasurement) -> None: ...
    def summary(self, student_id: int, skills: list[str] | None = None) -> ProgressSummary: ...

class CollegeService(Protocol):                                              # (P6 extends existing)
    def search(self, filters: CollegeFilters) -> list[CollegeCard]: ...      # transparent attributes, no opaque score
    def facts(self, college_id: int, attributes: list[str] | None = None) -> list[Fact]: ...  # each with provenance + freshness
```

The orchestrator's **tools** are thin adapters over these interfaces (as `app/ai/tools.py`
already is over `services/`), so the REST API and the LLM hit the same validated code.

## 4. Orchestrator context assembly

The prompt is assembled from small, separately-owned parts — never one giant prompt:

| Part | Owner | Size budget |
|---|---|---|
| Policy (safety, honesty, provenance rules) | `ai/prompts/policy.md` | fixed, ~800 tokens |
| Reply-language instruction | `ai/language.py` | ~60 |
| Student snapshot (stage, stream, track, language pref) | Profile | ~150 |
| Counselling state: open threads, next step | Memory (P2) | ~300 |
| Retrieved memories + timeline excerpts | Memory (P2) | ~600 |
| Session history (token-budgeted, oldest compressed) | Conversation | ~2 500 |
| Tool schemas | Tools registry, filtered by intent | ~1 500 |

## 5. Cross-cutting

- **Config**: pydantic-settings, `.env` only; provider names chosen by config (`LLM_PROVIDER=openrouter`).
- **Auth**: JWT for students; per-device key for the Pi (replaces today's "loopback is trusted"
  rule once the API can be remote). Every student-scoped query filters by the token's student id
  in a shared dependency — no endpoint takes a `student_id` from the client.
- **Resilience**: every outbound call has connect/read timeouts; retries with jittered backoff
  on 429/5xx only before the first streamed byte; per-provider circuit breaker so a dead TTS
  degrades to text instead of stalling turns.
- **Rate limiting**: per-student and per-device token buckets on conversation and LLM-backed endpoints.
- **Observability**: JSON logs with `request_id`/`session_id`/`turn_id` (the edge sends the same
  `turn_id`, so one grep shows the whole turn across both sides); per-turn latencies stored on
  the message row; `/api/health` reports each provider's last success/failure.
- **Encryption**: TLS when the API is remote; Postgres disk encryption is the host's job; the
  sensitive memory columns (doc 03) are encrypted at the application layer with a key from env.

## 6. Deployment: everything on the Pi 5 (8 GB) — decision D9

The "server" is a process, not a machine: the API listens on `127.0.0.1:8000` on the same
Pi as the desktop app (as `start.sh` / `run_kiosk.sh` already do), and PostgreSQL joins it
in Phase 2. Nothing is reachable from the network unless deliberately exposed.

| Process | Est. RAM | Notes |
|---|---|---|
| Desktop app (Qt + GIFs + Vosk + Silero VAD) | ~400 MB | Vosk already measured ~100 MB |
| API (uvicorn, 1 worker) | ~200 MB | |
| PostgreSQL + pgvector (P2+) | ~150–300 MB | small dataset |
| Local embedding model, if not using an API (P2+) | ~300 MB | multilingual-e5-small class |

Comfortable on 8 GB. LLM, STT and TTS stay in the cloud by default; running those locally on
the Pi is not realistic at conversational latency.
