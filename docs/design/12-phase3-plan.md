# 12 — Phase 3 plan: Assessment

Scope (spec §10, §11, §20, §32, §34 Phase 3): interest, aptitude and skill assessments, the
academic profile, and career exploration from the results — voice-first in English, Hindi and
Hinglish, with reassessment history. Schema: doc 02 §6; API: doc 07 §4. The career knowledge
graph, new careers and pathways are Phase 4; skill progress over practice and projects is
Phase 5.

## What exists, and what changes

| Today | Phase 3 |
|---|---|
| One 33-question conversational quiz (`seed/assessment_questions.json`), English only | Five versioned instruments, every item in English and Hindi |
| Interests only — subjects, RIASEC, a few values | + aptitude (numerical, logical, verbal), skills, a coding check, academic marks, how you learn |
| One `career_assessments` row with a ranked list | Attempts, responses and per-dimension scores, so retakes can be compared |
| "Your best match: X", a % fit per career | **No single answer** (spec §10): careers in bands — strong / potential / needs exploration — each with why, strengths, development areas, things to try, questions to ask yourself |
| "Must-haves" silently cost 25 % | A low must-have becomes a *question* ("Doctors see blood every day — could you spend a day at a clinic to find out?"), never a hidden penalty |
| MAYA's `assess_career_fit` tool invents 0–10 ratings from chat | Removed. MAYA reads the stored results, compares retakes, and suggests an assessment when there isn't one |

## Decisions

| ID | Decision | Why |
|---|---|---|
| P3-1 | **Instruments live as versioned JSON files in the repo** (`app/assessment/instruments/`), synced into `assessment_instruments`/`assessment_items` at start-up. A content change without a version bump fails a test (content hash) | Reviewed like code; every attempt records exactly which version it answered |
| P3-2 | **The server decides the next item**; the Pi app only shows and listens | One source of truth for branching, back/skip/resume — touch, voice and MAYA see the same state |
| P3-3 | **Scores are honest counts, never norms.** Aptitude shows "7 of 10 right today", not an IQ or percentile; every score carries how many items it rests on | There are no Indian norms for these items; claiming a percentile would be invented |
| P3-4 | **Aptitude has two parallel forms (A, B)**; a retake gets the form you haven't seen | Same items twice would inflate "Main kitna improve hua hoon?" |
| P3-5 | **Alignment is rule-based and explainable**, every reason pointing at a score; MAYA (the LLM) only *narrates* it | Spec §10 "explain WHY"; reproducible; testable |
| P3-6 | A snapshot of the career directions is stored each time an attempt completes (`career_alignment_snapshots`), instead of doc 02's per-attempt `career_alignments` | Directions combine several instruments; a snapshot records exactly what was said and from which attempts |
| P3-7 | **Assessment results are account data**, like class and marks: stored with the account, used by MAYA in conversation, deletable per attempt. Timeline events and memory items about them follow the Phase 2 memory consent | The student takes an assessment to get results. *Legal review should confirm this along with the DPDP consent question* |
| P3-8 | Voice answers: matched **on the Pi** first (option keywords in English/Hindi/Hinglish, "option B", numbers incl. Hindi number words); only if that fails, a quick LLM call interprets the answer | Most answers cost no extra time; unusual phrasing still works |
| P3-9 | Spatial reasoning (needs pictures) and new careers (cybersecurity, robotics…) are left out | Pictures don't work by voice; careers belong to Phase 4's knowledge model |

## Instruments

| Key | Category | Items | Time | Measures → dimension keys |
|---|---|---|---|---|
| `interests_v1` | interest / work style / values / learning | 33 today + 4 "how you learn" (branching, ~28 asked) | ~6 min | subjects, RIASEC, work style (`communication`, `outdoor`, `clinical`, `caregiving`), values (`stability`, `money`, `long_study`, `blood_ok`), `learning:*` |
| `aptitude_v1` | aptitude | 12 per form (4 numerical, 4 logical, 4 verbal; easy→hard), forms A/B | ~10 min | `aptitude:numerical`, `aptitude:logical`, `aptitude:verbal` |
| `skills_v1` | skill (self-report) | 8 skills, each "which is most like you" with concrete levels ("I've followed a tutorial" … "I've built something others use") | ~3 min | `skill:programming`, `skill:speaking`, `skill:writing`, `skill:design`, `skill:hands_on`, `skill:leadership`, `skill:organising`, `skill:english` |
| `coding_check_v1` | skill (measured) | 8 short pseudo-code reading problems, screen-first | ~6 min | `skill:programming_measured` |
| `academic_v1` | academic | latest marks per subject (list depends on class and stream) | ~2 min | `subject:*`; also written to `academic_records` |

Goals and constraints are not a questionnaire: Phase 2 memory already captures them from
conversation, and the directions screen lists them as "things you told MAYA to weigh".

## Alignment (career exploration)

For each of the 27 careers in `careers.json` (Phase 4 adds more):

- **Components** (spec §10's example):
  - `interest` is today's weighted fit over subject and RIASEC dimensions.
  - `work_style` covers the work-style and values dimensions.
  - Measured dimensions come from a new `career_needs.json`, e.g. CSE needs logical 3, numerical 2, mathematics 3 and programming 2.

  Each component carries its score, how many items it rests on, and its source.
- **Band**, with evidence required:

  | Band | When |
  |---|---|
  | **Strong** | interest ≥ 0.65, no must-have below 0.35, and every weight-3 measured need ≥ 0.4 (or not yet measured) |
  | **Potential** | interest ≥ 0.5; or ability ≥ 0.7 with interest ≥ 0.4 |
  | **Needs exploration** | interest 0.35–0.5, or high interest but a low must-have |
  | **Less likely** | interest < 0.35. Shown collapsed, never hidden |

- **Strengths**: needed components ≥ 0.7, worded from the student's own results ("logical reasoning — 8 of 10 right").
- **Development areas**: needed components < 0.55, each with a concrete next step.
- **Questions to investigate**: each one comes from a low must-have, an unmeasured need ("take the aptitude check to see"), or high interest with no experience yet, plus the career's own questions to ask yourself (new content, 2 per career).
- **Grouping by domain**: careers are grouped by domain, Technology → CSE, AI & Data, ECE… (spec §11).

Templates exist in English and Hindi; MAYA explains them in Hinglish when that's how the student talks.

## Steps

### Step 0 — Schema and instrument loading
- **Migration:** `assessment_instruments` (key, version, category, stages, title {en,hi}, est_minutes, scoring_method, status, content_sha), `assessment_items` (key, section, prompt/speak {en,hi}, item_type `choice`|`anchored`|`problem`|`marks`, options, scoring, requires, form, difficulty, sort), `assessment_attempts` (student, instrument + version, form, mode, language, status `in_progress`|`completed`|`abandoned`, started/completed, legacy_assessment_id), `assessment_responses` (attempt, item, answer, transcript, interpreted_by `touch`|`keywords`|`llm`, response_ms, skipped), `assessment_scores` (attempt, dimension_key, score 0–1, n_items, detail), `career_alignment_snapshots` (student, engine_version, inputs, results).
- **Loader:** the instrument files are synced at start-up and `seed`. A change without a version bump is refused.

### Step 1 — Content
- Port `interests_v1` (+ Hindi, + how you learn).
- Write `aptitude_v1` forms A/B, `skills_v1`, `coding_check_v1` and `academic_v1`.
- Write `career_needs.json` (27 careers) and the bilingual result templates.
- **Validation tests:** every item has English and Hindi; every option is scored; forms are balanced by dimension and difficulty; aptitude answers are unambiguous; no dangling dimension keys.

### Step 2 — Assessment service and scoring
- start / answer / back / skip / resume (an unfinished attempt resumes for 7 days) / complete.
- Branching via `requires`; the form is chosen for retakes.
- **Scoring by method:**
  - interests: earned ÷ possible, as today
  - aptitude and coding: correct ÷ asked, per dimension
  - skills: anchored level → 0–1
  - marks: percentage → 0–1

### Step 3 — Alignment engine
- Components, bands, strengths, development areas, questions and domain tree.
- A snapshot is taken on each completion.
- Deterministic: the same inputs give the same directions.

### Step 4 — APIs and the old data
- `GET /api/assessment/instruments`
- `POST /api/assessment/start|answer|back`
- `POST /api/assessment/interpret` (the LLM fallback)
- `GET /api/assessment/result|history`
- `DELETE /api/assessment/attempts/{id}`
- `GET /api/careers/directions[/{career_key}]`

The 2 existing `career_assessments` rows become `interests_v1` attempts. The old endpoints keep working (the web app) by going through the new service.

### Step 5 — Voice answers in three languages
- On the Pi: option keywords in English, Hindi and Hinglish; letters ("B", "option B", "बी"); numbers as digits and as English or Hindi words (0–100).
- Then `interpret` as the fallback.
- Questions are spoken in the student's language (Hindi text for Hindi/Hinglish speakers, with the English shown small underneath).

### Step 6 — MAYA uses the results
- **Context:** a short assessments block in every reply's context.
- **Tools:**
  - `get_my_assessments` and `explain_direction`
  - `compare_assessments`, for "Main kitna improve hua hoon?" — only changes larger than the noise for that many items count as change
  - `suggest_assessment`, which sends `ui.suggest` so the Pi shows a tappable "Start the aptitude check (10 min)"
- **Memory:** with consent, `ASSESSMENT_COMPLETED` events go on the timeline.
- Remove `assess_career_fit`.

### Step 7 — Screens (800×480)
- **My assessment:** the instruments, last taken, resume or retake, and "How I've changed" (first vs latest per dimension, as bars).
- **Question runner:** choice, anchored, problem and marks items; voice and touch; back and skip; progress; EN/हिंदी.
- **Career directions:** domain tree with bands; each career opens why, strengths, development areas, things to try, questions, and "Talk to MAYA about this".

### Step 8 — Verification
- **Automated:**
  - scoring arithmetic and branching
  - form alternation on retake
  - no "best match" or single score anywhere in the output
  - every reason traceable to a score
  - Hindi completeness
  - voice matching in three languages
  - noise-aware comparison
  - deleting an attempt really deletes it
  - one student never sees another's results
- **Hands-on:** `phase3-test-script.md`, including a native speaker's read of the Hindi.

## Exit criteria

1. Every instrument can be completed by touch and by voice, in English and in Hindi/Hinglish, with back, skip and resume.
2. Results never name one career as *the* answer. Every band has reasons the student recognises from their own answers, and anything unmeasured is labelled as unmeasured.
3. A retake of the aptitude check uses the other form, and "How I've changed" only calls a change a change when it is bigger than the noise.
4. MAYA answers "Mere liye kaunse careers sahi hain?" and "Main kitna improve hua hoon?" from stored results, and offers an assessment when there are none.
5. Old assessments are migrated, the old endpoints still answer, and all earlier tests still pass.

## As built (2026-10-01) — what changed after the live rehearsal

A rehearsal with the real model, on the throwaway test database and with invented students,
turned up four problems. Each was fixed:

| Seen | Fixed by |
|---|---|
| The AI interpreter read "sattasi" (87) as 37 | **Marks and problem answers never go to a model.** They are matched on the Pi (which reads Hindi number words) or tapped. A model leaning towards the right answer to a problem would also quietly inflate a score |
| "Main kitna improve hua hoon?" compared the wrong assessment ("Thinking skills" vs the key `aptitude`) | Context lines carry each assessment's key. `compare_assessments` with no key compares everything retaken, and falls back to what was retaken when asked about something taken once |
| With no assessments, the model said "the button is on your screen" without calling `suggest_assessment` | MAYA's page shows "Start: What you enjoy" until a first assessment is done, so the button exists whatever the model does. The prompt also tells it to call the tool rather than describe it. gpt-4o-mini still sometimes calls it only on the next turn |
| The interpreter treated an unrelated answer as "skip" | Skip now needs an explicit request |

Also, skill levels are reported counted from 1 ("level 3 of 4"), matching how the four lines are
numbered on screen and read out. Your two existing `career_assessments` rows were from the old
slider tool (no question-by-question answers), so there was nothing to bring over. They stay
in the old table.

Rehearsal results:

- **Directions.** For a maths/computers student with mixed aptitude, CSE, AI & Data and pure
  science came out strong; ECE and aerospace potential.
- **Retakes.** The retake used form B. "Working with numbers 2 → 4 of 5" was called an
  improvement; logic and words "about the same".
- **Spoken answers.** "maths toh meri jaan hai" → *love*. "theek thaak, kabhi accha kabhi nahi"
  → not understood (correct: it's ambiguous).
- **Replies.** Typed replies took 2–3 s (non-streamed).
