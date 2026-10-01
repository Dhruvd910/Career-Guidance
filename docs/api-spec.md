# API Reference

Base URL: `http://<host>:8000`. Auth: `Authorization: Bearer <token>` from
`/api/auth/register` or `/api/auth/login`, required on every endpoint below except where
noted "public." Interactive docs are also available live at `/docs` (FastAPI/Swagger).

## Auth

| Method & path | Auth | Body | Notes |
|---|---|---|---|
| `POST /api/auth/register` | public | `{email, password, name, class_level}` | Creates `User` + `StudentProfile` together, returns `{access_token, token_type}` |
| `POST /api/auth/login` | public | `{email, password}` | Returns a token |

## Student profile

| Method & path | Body / Query | Notes |
|---|---|---|
| `GET /api/student/profile` | — | Current student's profile |
| `PUT /api/student/profile` | Partial profile fields | Any subset of `name, class_level, school_board, state, domicile_state, category, preferred_language, preferred_study_locations, knows_career_goal, target_exam_code, onboarding_completed`. `target_exam_code` is what the student is aiming at (`JEE_MAIN`/`NEET_UG`, or `careers` while still exploring) — college, mock-test and career suggestions follow it, and it is given to MAYA so she stays on that track. Saving an exam profile sets it too; send an explicit `null` to clear it |
| `POST /api/student/academic-record` | `{academic_year, class_level, board_percentage?, subject_marks}` | Appends a record |
| `GET /api/student/onboarding/next-step` | — | Drives the dynamic onboarding flow (§3/§33) — returns the next step key + prompt, never re-asks for known fields |

## Exams

| Method & path | Notes |
|---|---|
| `GET /api/exams` | Catalog: `JEE_MAIN`, `JEE_ADVANCED`, `NEET_UG` (extensible per §48) |
| `POST /api/exams/profile` | Upsert the student's profile for one exam (`exam_code` + status/rank/percentile/preferences) |
| `GET /api/exams/{exam_code}/profile` | 404 if none saved yet |

## Mock tests

| Method & path | Notes |
|---|---|
| `POST /api/mock-tests` | `{exam_code, test_name, test_date, total_score, max_score, percentile?, estimated_rank?, subject_scores}` |
| `GET /api/mock-tests/history?exam_code=` | List, optionally filtered |
| `GET /api/mock-tests/dashboard?exam_code=` | Aggregated trend/average/weak-subject dashboard (§13); `estimated_rank_range` is explicitly labeled an estimate |

## Practice papers (MCQ mock tests)

Questions are written for this app, not copied from past papers; each carries
`verification_status = "practice_content"` with that provenance. Marking follows the real
exams: +4 correct, −1 wrong, 0 unanswered.

| Endpoint | Notes |
| --- | --- |
| `GET /api/practice/options?exam_code=` | Subjects available in the bank, what a subject test asks, the full paper the bank can fill (count, minutes, subject breakdown), and the real paper's size for comparison |
| `POST /api/practice/start` | `{exam_code, mode: "subject"\|"full", subject?}` → attempt id, duration, and the questions **without** `correct_index` or `explanation` |
| `POST /api/practice/{attempt_id}/submit` | `{answers: [{question_id, selected_index\|null}], seconds_taken?}` → score, per-subject breakdown, and a full review with the correct answer and explanation. Also records a `mock_tests` row so trends cover practice papers too. 409 if already submitted |
| `GET /api/practice/attempts` | Submitted attempts, newest first |
| `GET /api/practice/attempts/{id}` | One attempt with its review; 409 while unsubmitted, 404 if it belongs to someone else |

## Careers

| Method & path | Auth | Notes |
|---|---|---|
| `GET /api/careers` | public | Full career catalog (§49 career graph nodes) |
| `GET /api/careers/{id}` | public | One career's detail |
| `GET /api/careers/key/{key}` | public | One career by its stable key (`cse`, `mbbs`, `law`…), including `details`: how to prepare, where to start this week, entrance exams, free resources, day in the job, roles, future scope, earnings with sources |
| `GET /api/careers/assessment/questions` | public | MAYA's question bank: personality, interests and subject deep-dives. Each question has options that score dimensions (subjects, RIASEC, clinical, caregiving…) and may `require` an earlier answer |
| `POST /api/careers/assessment` | required | `{assessment_type: "conversational", responses: {answers: {question_id: option_id}}}` → every career scored 0–100 against the answers (skipped questions count as neutral) and labelled Best match / Strong / Good / Worth exploring / Less likely / Not a natural fit, with `reasons`, `watch_outs` and `highlights` (what the answers say about the student). The older `{subject_interest, traits}` shape still works |

## Colleges

| Method & path | Auth | Notes |
|---|---|---|
| `GET /api/colleges?q=&exam_code=&state=&city=&ownership=&college_type=&course_name=` | public | Discovery/search (§14). `q` understands short names ("IIT Bombay", "NIT Trichy", "KGMU") and matches city or state. Researched colleges come first (best NIRF rank first), each with `nirf_rank` and `researched` |
| `GET /api/colleges/{id}` | public | Full profile incl. `courses_offered`, plus `profile` (researched: NIRF rank, fees & waivers, placements, teaching hospital, surroundings, sources — null if not researched yet) and `admission` (latest official closing ranks for open, gender-neutral, all-India seats: hardest and easiest program) |
| `GET /api/colleges/{id}/cutoffs?category=&branch_name=` | public | Official cutoffs (JoSAA / MCC), each with its `program` and `provenance` |
| `GET /api/colleges/{id}/fees` | public | Per-course-offering fee breakdown + `approximate_annual_cost` |
| `GET /api/colleges/{id}/hostel` | public | |
| `GET /api/colleges/{id}/placements` | public | Engineering: `placement_percentage`/packages. Medical: `extra` (internship stipend, PG pathways, etc.) — never forces "placement" language onto medical colleges (§18) |
| `GET /api/colleges/{id}/nearby` | public | Sample data — never live availability (§19) |
| `GET /api/colleges/{id}/reviews` | public | User-generated, explicitly not verified fact |
| `POST /api/colleges/{id}/reviews` | required | `{rating, text, tags}` |
| `POST /api/colleges/compare` | public | `{college_ids: [2-4 ids]}` → one row per college with the same `profile` and `admission` as above (`approximate_annual_cost` falls back to researched tuition), + an LLM-generated `ai_summary` grounded only in those rows (null if AI isn't configured) |

**Where the college data comes from**: cutoffs are official — JoSAA 2026 round 5 opening
and closing ranks (every IIT, NIT, IIIT and GFTI) and MCC NEET-UG 2026 rounds 1–2 allotments
(All-India counselling). Researched profiles for the most-compared colleges live in
`apps/api/app/seed/data/college_profiles.json`, every figure tied to a named source.

Every `provenance` object is `{source, source_url, academic_year, last_verified,
verification_status}`; `verification_status: "unverified_demo"` is how the frontend
renders the DEMO DATA banner.

## Predictions & counselling

| Method & path | Auth | Body | Notes |
|---|---|---|---|
| `POST /api/predict/jee` | public | `PredictionRequest` (below) | |
| `POST /api/predict/neet` | public | `PredictionRequest` | Same engine as JEE — the exam determines the eligible college pool |
| `POST /api/counselling/preference-list` | public | Same shape as `PredictionRequest` | Returns a Dream→Safe ordered list (§21) |

`PredictionRequest`: `{exam_code, rank?, percentile?, score?, category, category_rank?,
gender?, quota?, domicile_state?, preferred_branches?, preferred_states?,
college_type_preference?, budget_max?}`.

- No rank yet? A JEE Main `percentile` or NEET `score` becomes an estimated rank (JEE Main:
  (100 − P) × 15,38,468 / 100 candidates; NEET: the 2026 marks-vs-rank table). The response
  says so: `rank_estimated`, `rank_basis`. With none of the three → 400 saying what to enter.
- JoSAA rules: OPEN seats compare the overall rank, reserved seats the `category_rank`
  (without it, only OPEN seats are shown and `notes` explains why); `gender: "female"` adds
  the female-only pool; home-state seats only for students domiciled there. IIT seats use
  the JEE Advanced rank. NIT/IIIT/GFTI B.Arch and B.Plan are left out (they're allotted on
  JEE Main Paper 2 ranks).
- MCC rules (NEET): every category is allotted by All-India Rank; AIQ, open, deemed and the
  student's own Delhi/Puducherry quota seats are considered.
Response includes a `band` (`high_probability`/`possible`/`ambitious`) per result, each
with a full `explanation` (years considered, actual historical closing ranks, rounds
considered, data freshness) — see `docs/architecture.md` §5 for how bands are computed.
Predictions are intentionally left public (no auth) so a visitor can try one before
creating an account.

## Roadmap & shortlist

| Method & path | Notes |
|---|---|
| `GET /api/roadmap` | Deterministic step-by-step roadmap (§33), templated by class level + exam status, plus `study_plan` for the student's exam: pacing phases, each subject's chapters (NCERT book and chapter, high-weight ones starred) and free resources with links |
| `GET /api/saved-items` | The student's "My Shortlist" (§38) |
| `POST /api/saved-items` | `{item_type, item_id, bucket?, notes?}` — `item_type` is `college\|branch\|career\|course`, `bucket` is `dream\|target\|safe` |
| `DELETE /api/saved-items/{id}` | |

## AI assistant

| Method & path | Notes |
|---|---|
| `POST /api/ai/chat` | `{message, conversation_id?}` → `{conversation_id, reply, tool_calls_used, ai_configured}`. `ai_configured: false` (with a plain-language explanation as the reply) when `OPENROUTER_API_KEY` isn't set — never a 500 |
| `POST /api/ai/voice-chat` | multipart: `audio` file + optional `conversation_id` query param → transcribes (Groq), runs the same chat pipeline, optionally returns base64 TTS audio (Cartesia). 503 if `GROQ_API_KEY` isn't set |
| `POST /api/ai/speak` | `{text}` → `{audio_base64, audio_content_type, tts_configured}`. Synthesizes any text via Cartesia (MAYA's replies, boot greeting, and questions she asks). Never errors on TTS failure — returns null audio and logs why. **No login needed from the device itself (loopback); any other caller needs a token** |
| `POST /api/ai/transcribe` | multipart `audio` → `{transcript}`. Speech-to-text only, no chat — used to fill form fields by voice (first-run name/class, keyboard dictation). Same loopback-or-token rule as `/speak`, since first-run happens before any account exists |
| `GET /api/ai/conversations/{id}` | Full message history for one conversation |

See `docs/architecture.md` §4 for the tool-calling architecture behind `/api/ai/chat`.
