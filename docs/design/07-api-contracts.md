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

## 2. Voice WebSocket protocol (P1) — as built

Connect: `ws://127.0.0.1:8000/api/ws/conversation?session_id=…` with `Authorization: Bearer
<student JWT>` (or `?token=` for clients that can't set headers). No token → closed with code
4401. A `session_id` that isn't the student's starts a new session instead. JSON control frames;
audio as binary frames that always directly follow the JSON frame announcing them.

**Edge → server**

| `type` | Fields | Meaning |
|---|---|---|
| `turn.audio` | `turn_id, encoding:"wav"` + 1 binary frame | One complete utterance (edge VAD already endpointed it), ≤ 2 MB |
| `turn.text` | `turn_id, text` | Typed input in the same session |
| `playback.ack` | `turn_id, seq` | Sentence `seq` finished playing |
| `turn.interrupt` | `turn_id, seq, played_ms` | Student barged in while sentence `seq` was `played_ms` in (sentences before it were heard whole) |
| `ping` | | keepalive → `pong` |

**Server → edge**

| `type` | Fields | Meaning |
|---|---|---|
| `session.ready` | `session_id, opening` | `opening` is null until Phase 2 ("where we left off") |
| `turn.transcript` | `turn_id, text, language, script, confidence` | What was heard (or typed); `language` is `en`/`hi`/`hinglish` |
| `turn.no_speech` | `turn_id` | The clip held no speech (incl. Whisper's "Thank you." in silence); nothing else follows |
| `turn.thinking` | `turn_id, activity?` | Mascot → thinking; `activity` = the tool being run, a cue for a filler line |
| `reply.delta` | `turn_id, seq, text` | Sentence `seq`, for the screen — always before any of its audio |
| `reply.audio` | `turn_id, seq, sample_rate, encoding:"pcm_s16le"` + 1 binary frame | A chunk of sentence `seq`'s speech, as it's synthesised; in order |
| `reply.done` | `turn_id, text, language, tool_calls_used` | No more for this turn |
| `turn.cancelled` | `turn_id` | Ack of an interrupt; nothing more follows for that turn |
| `error` | `turn_id?, code, message, retryable` | `stt_unavailable`, `llm_unavailable`, `tts_unavailable` (text still arrives), `internal_error`, `bad_message`, `audio_too_long` |

A new `turn.audio`/`turn.text` implicitly cancels a running turn (saved as heard up to the last
`playback.ack`). An interrupt after `reply.done` still counts: the saved reply is cut back to
what was heard. Bad frames get an `error` and never drop the connection.

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

## 8. Devices (deferred)

Per-device keys (`POST /api/devices/pair`, `DELETE /api/devices/{id}`) were planned for P1 but
deferred by decision D9: the API listens on 127.0.0.1 only, so every caller already *is* the
device. They come back when the API is reachable from anything else.

## 9. Cross-cutting

- Auth: JWT (existing), required on `/ws/conversation`. `/ai/speak` and `/ai/transcribe`
  stay open to loopback for the pre-account setup screens (device keys: §8).
- Rate limits: `/ws/conversation` 1 connection per device, 30 turns/min; LLM-backed REST
  endpoints 20/min/student. 429 with `retry_after`.
- OpenAPI at `/docs` stays the source of truth for REST; the WS protocol is documented here
  and pinned by an integration test that replays a recorded session.
