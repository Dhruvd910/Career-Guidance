# 14 — Phase 5 plan: Roadmap and progress

Scope (spec §18–21, §31, §32's "Mera next step kya hai?", §34 Phase 5):
- a class-aware, personalised roadmap
- milestones
- progress tracking
- roadmap versioning: changes when the student's situation changes, and history never destroyed

It builds on everything so far:
- stage and profile (Phase 1–2)
- assessments (Phase 3)
- the career graph (Phase 4)
- memory, for goals and the timeline (Phase 2)

Design: doc 09; schema: doc 02 §8; API: doc 07 §6.

## What exists, and what changes

| Today | Phase 5 |
|---|---|
| A fixed list of 6–8 steps chosen by class and exam status; recomputed every time, nothing stored | A **versioned roadmap tree**: stage → milestone → module → task, with history |
| Not personal beyond class and exam | Built from the **10 inputs of spec §18**: class, skill levels, academic profile, assessments, the career the student chose, goals, weekly time, location, board and progress so far. Each version stores them |
| No progress | **Progress per node** (survives new versions), and **skill progress over time** — initial vs current, from assessments and practice papers |
| Never changes | **Adapts** (spec §19): less time, a hard subject, a change of interest, a reassessment → a new version with the reason for every change. Old versions stay |
| JEE/NEET chapter-by-chapter study plan | Kept, inside the roadmap's *Entrance exams* module |

## Decisions

| ID | Decision | Why |
|---|---|---|
| P5-1 | **Structure is deterministic** — stage templates + the career graph + written rules. No LLM decides what goes in the roadmap; MAYA explains it | Doc 09. Testable, explainable, the same for the same inputs |
| P5-2 | **Versions are immutable.** Any change makes V(n+1) with a trigger, a rationale and a list of changes (added / removed / moved / parked, each with a reason). **Progress is stored per node key**, so "Python basics: done" in V1 is still done in V5 | Spec §19: "never destroy historical roadmap versions" |
| P5-3 | **The student chooses the focus career** — "Make this my focus" on a career page, or by telling MAYA, who confirms first. Without a focus, the roadmap is the stage's spine plus exploration of their top 2–3 directions | The student decides (spec §11). A roadmap can't assume a career |
| P5-4 | **Skill progress only from measurements** (assessments, practice papers). Ticking a module done is the student's own progress on the roadmap, labelled as such, and never becomes a "skill level" | Same honesty rule as Phases 3–4 |
| P5-5 | **Every adaptation is visible**: what moved, what was parked (never silently deleted), and why. Exam-critical modules are never dropped for lack of time — they're kept and other things are deferred | Spec §19, doc 09 §4 |
| P5-6 | **Time = hours a week for the roadmap, on top of school**; default 4 h. Scheduled in month windows, not dates | Students' weeks vary; months are honest precision |
| P5-7 | Out of scope: logging study minutes ("learning activities") and a separate projects table — projects are roadmap tasks with progress and evidence | Keeps the phase to the spec's essentials; easy to add later |

## The tree

| Stage band (from class or education stage) | The current stage's spine (spec §18) | Later stages shown |
|---|---|---|
| Class 6–8 | explore interests → basic maths → science exploration → programming curiosity → small projects → career exploration | Class 9–10 → 11–12 → Degree → Career |
| Class 9–10 | assessment → career exploration → stream choice → foundation skills → class 11–12 planning | Class 11 → 12 → Degree → Specialisation → Internship → Career |
| Class 11–12 | career decision → entrance exams → degree selection → college exploration → skill development → projects | Degree → Specialisation → Internship → Career |
| Dropper | exam strategy review → weak-area plan → mock tests → backup pathways | Degree → … |
| College | skill-gap analysis → specialisation → projects → internship → portfolio → job preparation | Career |

How each slot in the spine is filled:

| Slot | From |
|---|---|
| Foundation skills | the focus career's skills (graph), foundations first, in prerequisite order; age-appropriate for the stage, so advanced skills sit in later stages |
| Projects | the projects that build those skills (graph `developed_by`) |
| Stream choice | the streams that keep the focus open (graph); links to the stream explorer |
| Entrance exams | the common route's exams, with official sites; the JEE/NEET study plan when it applies |
| Degree selection | the common and alternative routes |
| College exploration | colleges in the student's state with an official programme |
| Assessment / career exploration | the checks not yet taken; the top directions |

Every node:
- has a stable key
- has a title, why, how, "done when" and resources, all in English and Hindi
- has hours, prerequisites and a month window
- refers back to the graph

Skills already measured strong are marked done, with the assessment as evidence. A low measured subject inserts a foundation module before what needs it.

## Adaptation rules (spec §19, doc 09 §4)

| Trigger | Rule |
|---|---|
| `time_budget` — "I only have 2 hours a day" | Reschedule at the new weekly hours. Optional modules (curiosity, extra projects) are **deferred** first, with the reason. Exam-critical and prerequisite modules are kept. Say what moved |
| `difficulty` — "Maths is difficult for me" (or a measured gap) | Insert a *Maths foundation* module before every module that builds on school maths |
| `interest_change` — "I no longer want AI, I like cybersecurity" | Add an **exploration branch** for the new career. Modules only the old focus needed are **parked**, not deleted. Shared ones (Python, maths) stay. The student can make the branch their focus |
| `reassessment` (automatic when an assessment completes) | Modules whose skill is now measured strong → done, with the assessment as evidence. New gaps → foundation modules |
| `focus` — "make cybersecurity my focus" | Rebuild around the new focus. The old focus's unique modules are parked |
| `manual` | Regenerate from the current inputs |

## Steps

### Step 0 — Schema
| Table | Holds |
|---|---|
| `roadmaps` | student, focus career, branches, hours per week, active version |
| `roadmap_versions` | version number, parent, trigger, rationale, inputs snapshot — immutable |
| `roadmap_nodes` | per version: node key, parent, kind, stage, title / detail `{en,hi}`, prerequisites, hours, window, graph refs, state `active`/`deferred`/`parked`, sort order |
| `roadmap_progress` | roadmap + node key → status, percent, evidence |
| `roadmap_changes` | per version: what changed and why |
| `skill_measurements` | student, skill key, value, source kind and id, when |

### Step 1 — Stage templates
`app/roadmap/templates.yaml`: five bands, their stages and spine milestones with slots, all in English and Hindi. Validated like the instruments.

### Step 2 — Generator
Snapshot the inputs → build the tree (spine + graph modules + gap modules + branches) → mark measured skills done → schedule (prerequisite order, packed into months by hours a week) → diff against the last version → store a new version only if something changed.

### Step 3 — Adaptation and progress
- `recalculate(trigger)` with the rules above
- set the focus, add a branch, update a node's progress (with evidence)
- reassessment hook on assessment completion
- timeline events, with the memory permission: `ROADMAP_CREATED`, `ROADMAP_UPDATED`, `MILESTONE_COMPLETED`, `FOCUS_CHOSEN`

### Step 4 — Skill progress
`skill_measurements`:
- **From assessments:** filled when an attempt completes. Assessment dimensions map to graph skills through `measured_by`.
- **From practice papers:** subject accuracy, filled when a paper is submitted.
- **Backfilled** from completed attempts.

The progress summary shows, per skill, its initial value, current value and points over time with their sources. It also shows roadmap completion, milestones, projects, assessments taken and goals.

### Step 5 — APIs (doc 07 §6)
- `GET /api/roadmap` (active version with per-node progress; `?version=n` for history)
- `GET /api/roadmap/versions`, `GET /api/roadmap/changes?version=`
- `POST /api/roadmap/recalculate`, `POST /api/roadmap/focus`
- `GET /api/roadmap/next-step`
- `GET /api/progress`, `POST /api/progress/update`

The old template response moves to `GET /api/roadmap/legacy`, still used by the study plan screen.

### Step 6 — MAYA
**Context:** a short roadmap block — focus, current stage, next step, % done, last change.

**Tools:**
- `get_my_roadmap`
- `roadmap_next_step` ("Mera next step kya hai?")
- `adjust_roadmap` (the §19 triggers; she confirms with the student first, then explains the changes)
- `set_roadmap_focus`
- `update_roadmap_progress` ("I finished the Python course")
- `my_progress` (initial → current)

The old `generate_roadmap` tool goes.

### Step 7 — Screens (800×480)
- **My roadmap** (spec §31): stages top to bottom, the current one open with ✓ / % / ○.
- **A node:** why, how, done-when, resources (QR), mark started/done, *Ask MAYA about this*.
- **Controls:** *What changed* (latest diff) and *Versions*, plus *I have less time* and *Change focus*.
- **My progress:** skills as initial→current bars, roadmap completion, milestones and projects.
- **Make this my focus** on career pages.
- **The JEE/NEET study plan** stays one tap away.

### Step 8 — Verification
- **Automated:**
  - each band's spine
  - the same inputs give the same roadmap
  - prerequisite order
  - each adaptation rule (and that nothing exam-critical is dropped)
  - versions immutable; progress survives versions
  - measured-only skill progress
  - consent-gated events
  - one student never sees another's roadmap
- **Live rehearsal** with the real model on the test database: the three §19 sentences, "Mera next step kya hai?" and "Main kitna improve hua hoon?".
- **Hands-on test:** `phase5-test-script.md`.

## Exit criteria

1. A class 8, a class 10, a class 12 and a college student get different roadmaps matching spec §18, and each version records its inputs.
2. Choosing AI as the focus puts the graph's skills into the roadmap in prerequisite order, with projects. Skills already measured strong show as done, with the evidence.
3. The three sentences of spec §19 each produce a new version with stated changes. V1 is unchanged, and progress carries over.
4. MAYA answers "Mera next step kya hai?" from the roadmap, and "Main kitna improve hua hoon?" with skills' initial → current.
5. The progress screen shows skills initial vs current visually, roadmap completion, milestones and projects.
6. All Phase 1–4 tests still pass.
