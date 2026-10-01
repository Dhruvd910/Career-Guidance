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
| `ui.suggest` | `turn_id, action:"open_assessment", instrument_key, title {en,hi}, est_minutes, reason` | (P3) MAYA offers something on screen — a button to start an assessment. Never acted on without a tap |
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

## 4. Assessment (P3) — as built

| Method & path | Notes |
|---|---|
| `GET /api/assessment/instruments` | each instrument: title/about `{en,hi}`, est_minutes, times_taken, last_completed, in_progress `{attempt_id, answered}` |
| `POST /api/assessment/start` | `{instrument_key, language: en\|hi, mode}` → a view: `{attempt_id, status, language, instrument, complete:false, item, progress {answered, estimate}, can_go_back}`. Resumes an unfinished attempt (≤ 7 days); a retake of aptitude gets the other form |
| `POST /api/assessment/answer` | `{attempt_id, item_key, answer: {option}\|{value}, skipped?, transcript?, interpreted_by: touch\|keywords\|llm, response_ms?}` → the next view, or `{complete:true, result}` |
| `POST /api/assessment/back` | `{attempt_id}` → the previous item again, with its answer |
| `POST /api/assessment/interpret` | `{attempt_id, item_key, transcript}` → `{answer: {option}\|{value}\|null, skip}` — the LLM fallback for spoken answers; records nothing |
| `GET /api/assessment/result?attempt_id=` | scores per dimension: `{dimension, group, label {en,hi}, score 0–1, n_items, detail, says {en,hi}}` (e.g. "7 of 10 right"); problems also get a `review` with the right answers and why |
| `GET /api/assessment/history?instrument_key=` | completed attempts oldest first + `since_first`/`since_previous`: per dimension `change` +1/0/−1, non-zero only beyond the noise |
| `DELETE /api/assessment/attempts/{id}` | real delete: answers, scores, the directions worked out from them, the timeline entry |
| `GET /api/careers/directions` | `{ready, missing, inputs, domains: [{domain, label, best_band, careers: [...]}], summary {strong, potential, explore, weak}}`; each career: band + label, components, why, strengths, development_areas (with next_step), questions, not_measured, things_to_try, education_path, exams, evidence. No overall score, no ranking |
| `GET /api/careers/directions/{career_key}` | one career from the above |

An item view: `{key, type: choice\|anchored\|problem\|marks, section, prompt {en,hi}, options [{key, label {en,hi}, keywords {en,hi,hinglish}}], say (what MAYA reads out, in the attempt's language), answer (when going back), code?}`.

## 5. Careers (P4) — as built

| Method & path | Notes |
|---|---|
| `GET /api/career/options` | Phase 3's directions grouped by graph domain, each career with `domain`, `required_education` (degree, class 11-12 subjects, streams, exams with official URLs), `typical_pathway` (steps: stream → exam → degree → roles), `alternative_pathways`, `skills` (each with the student's result where measured, else `not_measured`), `skill_gaps` (measured only), `foundation_gaps`, `colleges` `{total, in_state}` and `from_memory` reasons. Without an interests check: `{ready: false, tree, from_memory}` |
| `GET /api/career/{key}` | one career in full: the above plus `learning_path` (prerequisite order, with projects/courses), `related`, `colleges_in_state`, `sources` (curated vs official, unreviewed count). Works without assessments (no band) |
| `GET /api/career/explore` | the domain tree (spec §11) |
| `GET /api/career/stream/{pcm\|pcb\|pcmb\|commerce\|humanities}` | `open`, `if_you_add` (an optional subject), `closed` — each with the deciding degree and subjects |
| `GET /api/career/{key}/colleges?state=&city=&limit=` | colleges with an official JoSAA/MCC 2026 programme on a route in; never fees/facilities |
| `GET /api/skills/{key}/path` | prerequisite-ordered steps, each with what builds it |
| `GET /api/careers…` | the older catalogue and long-form guides, unchanged |

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
