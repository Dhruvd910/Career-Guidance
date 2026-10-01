# 07 — API contracts

Base: `/api`. Existing endpoints (docs/api-spec.md) keep working; new ones are added
alongside. Everything below needs a student JWT unless marked. **No endpoint accepts a
`student_id` from the client** — the student is always the token's student. Errors use one
shape: `{"error": {"code": "string", "message": "string", "retryable": bool}}`.

## 1. Conversation (P1 minimal, P2 full)

| Method & path | Body → Response |
|---|---|
| `POST /api/conversation/start` | `{channel: "voice"\|"text", device_id?}` → `{session_id, opening: {text, language, reason: "greeting"\|"resume_thread"\|"next_step"}, state: CounsellingState\|null}` |
| `POST /api/conversation/message` | `{session_id, text, turn_id?}` → `{turn_id, reply: {text, language}, tool_calls_used: [str], citations: [Citation]}` (non-streaming fallback; also what text-only clients use) |
| `POST /api/conversation/end` | `{session_id}` → `202 {summary_status: "scheduled"}` |
| `WS /api/ws/conversation` | streaming voice protocol, §2 |

`CounsellingState` = `{current_counselling_topic, current_problem, decision_status,
open_questions[], previous_actions[], next_step, last_session: {id, ended_at}}`.

## 2. Voice WebSocket protocol (P1)

Connect: `wss://host/api/ws/conversation?session_id=…` with `Authorization: Bearer <student
JWT>` and `X-Device-Key: <device key>`. JSON control frames; audio as binary frames that
always follow the JSON frame announcing them.

**Edge → server**

| `type` | Fields | Meaning |
|---|---|---|
| `turn.audio` | `turn_id, sample_rate, encoding:"pcm_s16le"\|"wav", duration_ms` + 1 binary frame | One complete utterance (edge VAD already endpointed it) |
| `turn.text` | `turn_id, text` | Typed input in the same session |
| `playback.ack` | `turn_id, seq` | Chunk `seq` finished playing (lets server know what was heard) |
| `turn.interrupt` | `turn_id, last_played_seq, played_ms_in_seq` | Student barged in; stop everything for this turn |
| `ping` | | keepalive (every 15 s) |

**Server → edge**

| `type` | Fields | Meaning |
|---|---|---|
| `session.ready` | `session_id, opening?` | |
| `turn.transcript` | `turn_id, text, language, script, confidence` | Show what was heard |
| `turn.thinking` | `turn_id, activity?: "looking_up_colleges"\|…` | Mascot → thinking; optional short spoken filler |
| `reply.delta` | `turn_id, seq, text` | Text of sentence `seq` (for the screen) |
| `reply.audio` | `turn_id, seq, sample_rate, encoding:"pcm_s16le"` + 1 binary frame | Audio for sentence `seq`, in order |
| `reply.done` | `turn_id, text, citations, tool_calls_used` | No more audio for this turn |
| `turn.cancelled` | `turn_id` | Ack of interrupt; anything after this for that turn is dropped |
| `error` | `turn_id?, code, message, retryable` | e.g. `stt_failed`, `llm_timeout`, `tts_unavailable` (text still arrives) |

Ordering guarantees: per turn, `reply.audio` seq is strictly increasing; a new `turn.audio`
implicitly interrupts the previous turn. Max utterance 30 s / 2 MB; max 1 active turn per session.

## 3. Student, memory, timeline (P2)

| Method & path | Notes |
|---|---|
| `GET /api/student/profile` / `PUT` | existing; P2 adds stage, stream, goals/constraints summaries |
| `GET /api/student/memory?kind=&q=` | memory items visible to the student, with source session |
| `DELETE /api/student/memory/{id}` | real delete; logged in `data_requests` |
| `GET /api/student/timeline?from=&to=&types=` | `student_events`, newest first, paginated |
| `GET /api/counselling/current-state` | `CounsellingState` |
| `GET /api/counselling/history?cursor=` | sessions with summary, threads touched |
| `GET /api/counselling/threads` / `PATCH /api/counselling/threads/{id}` | student can park/resolve a topic |
| `POST /api/consent` / `GET /api/consent` | consent kinds from doc 02 §2 |

## 4. Assessment (P3)

| Method & path | Notes |
|---|---|
| `GET /api/assessment/instruments` | available for the student's stage |
| `POST /api/assessment/start` | `{instrument_key}` → `{attempt_id, item}` |
| `POST /api/assessment/answer` | `{attempt_id, item_key, answer, transcript?, response_ms}` → `{next_item}` or `{complete: true}` |
| `GET /api/assessment/result?attempt_id=` | dimension scores + career alignments (`strong`/`potential`/`explore`, strengths, development_areas, reasons, questions_to_investigate). Never a single "your career is X" |
| `GET /api/assessment/history?instrument_key=` | for reassessment comparisons |

## 5. Careers (P4)

| Method & path | Notes |
|---|---|
| `GET /api/career/options` | personalised directions: `[{career_key, name, domain, alignment_band, why_it_may_fit[], strengths[], skill_gaps[], education_required, typical_pathway, alternative_pathways[], explore_next[], questions_to_ask_yourself[]}]` |
| `GET /api/career/{key}` | career guide + graph neighbourhood (skills, degrees, related careers) |
| `GET /api/careers…` | existing catalog endpoints kept |

## 6. Roadmap & progress (P5)

| Method & path | Notes |
|---|---|
| `GET /api/roadmap` | active version as a tree with per-node progress; `?version=` for history (replaces today's template response; old shape kept under `/api/roadmap/legacy` until the desktop page moves) |
| `GET /api/roadmap/versions` | `[{version_no, created_at, trigger, rationale, change_count}]` |
| `POST /api/roadmap/recalculate` | `{trigger: {kind: "time_budget"\|"difficulty"\|"interest_change"\|"reassessment"\|"manual", detail}}` → new version + `changes[]` |
| `GET /api/roadmap/next-step` | first actionable node + why |
| `GET /api/progress?skills=` | per-skill series: `{skill_key, initial, current, points:[{at, value, source}]}` |
| `POST /api/progress/update` | `{node_key?, skill_key?, status?, percent?, evidence?}` |

## 7. Colleges (P6)

| Method & path | Notes |
|---|---|
| `GET /api/colleges?career=&degree=&state=&near=lat,lng&radius_km=&budget_max=&exam=&hostel=&medical=` | cards with transparent attributes, each attribute a `FactView` |
| `GET /api/college/{id}` | all facts grouped (academic, financial, campus, location, admissions) |
| `GET /api/college/{id}/sources` | every source document used, tier, retrieved/verified dates |
| `POST /api/colleges/compare` | existing; rows become `FactView`s, conflicts shown |

`FactView` = `{value, unit, status, verified_label, academic_year, source_name, source_url,
conflict?: [{value, source_name, source_url}]}`.

## 8. Devices (P1)

| Method & path | Notes |
|---|---|
| `POST /api/devices/pair` | admin/student token → `{device_id, device_key}` shown once; stored hashed |
| `DELETE /api/devices/{id}` | revoke |

## 9. Cross-cutting

- Auth: JWT (existing). Device key required on `/ws/conversation`, `/ai/speak`,
  `/ai/transcribe` once the API is reachable from anything but loopback.
- Rate limits: `/ws/conversation` 1 connection per device, 30 turns/min; LLM-backed REST
  endpoints 20/min/student. 429 with `retry_after`.
- OpenAPI at `/docs` stays the source of truth for REST; the WS protocol is documented here
  and pinned by an integration test that replays a recorded session.
