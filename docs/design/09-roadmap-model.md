# 09 — Roadmap data model (Phase 5)

## 1. Concepts

- **Roadmap**: one per student per active direction (exploring two directions = two
  roadmaps, or one roadmap with `exploration_branch` nodes — the latter is the default).
- **Version**: an immutable snapshot of the whole tree. Any change creates V(n+1) with a
  `trigger`, `rationale` and a list of `roadmap_changes`. Old versions are never edited.
- **Node**: stage → milestone → module → task. Each node has a `node_key` that stays the same
  across versions, so **progress is stored per node_key, not per version**: finishing
  "Python basics" in V1 is still finished in V2.

```
roadmap ─┬─ version 1 (trigger: initial assessment)
         ├─ version 2 (trigger: "I only have 2 hours a day")      changes: est_hours ↓, due windows ↑
         └─ version 3 (trigger: interest_change AI → cybersecurity) changes: + exploration_branch
                    │
                    └─ nodes (node_key, parent_key, stage, kind, title{en,hi}, prerequisites,
                              est_hours, due_window, kg_refs[skill:python, career:…])
progress(roadmap_id, node_key) → status, percent, evidence
```

## 2. Node schema

```json
{
  "node_key": "module:python_basics",
  "parent_key": "stage:class_10",
  "kind": "module",
  "title": {"en": "Python basics", "hi": "पायथन की शुरुआत"},
  "detail": {"why": "Programming is a core skill for AI/ML and software careers",
             "how": ["Variables, loops, functions", "2 mini projects"],
             "resources": [{"title": "…", "url": "…", "free": true}],
             "done_when": "Can write a 50-line program that reads input and uses functions"},
  "prerequisites": ["module:maths_foundation_algebra"],
  "est_hours": 30, "due_window": {"from": "2026-11", "to": "2027-01"},
  "kg_refs": ["skill:python"], "sort": 2
}
```

## 3. Generation

Inputs (spec §18) are snapshotted into `inputs_snapshot` so every version is explainable:
education stage, current skill levels, academic profile, latest assessment, chosen /
explored career directions, goals, weekly study time, location, board, current progress.

```
stage template (deterministic, reviewed content)
  + career direction modules (from graph: requires_skill + prerequisites, filtered to
    what's age-appropriate for the stage)
  + gap modules (required level − measured level > threshold)
  − modules already done (progress)
  → schedule: topological order by prerequisites, packed into weeks by study_hours_per_week
  → LLM only writes the human explanations (why/how wording) for the student's language;
    it does not decide structure
```

Stage templates (`roadmap/templates/*.yaml`):

| Stage | Spine |
|---|---|
| Class 6–8 | explore interests → basic maths → science curiosity → programming curiosity → small projects → career exploration |
| Class 9–10 | assessment → career exploration → stream exploration (PCM/PCB/commerce/humanities) → foundation skills → class 11–12 planning |
| Class 11–12 | career decision → entrance exams (existing NCERT study plan plugs in here) → degree selection → college exploration → skill development → projects |
| Dropper | exam strategy review → weak-area plan → mock schedule → backup pathways |
| College | skill-gap analysis → specialisation → projects → internship → portfolio → job preparation |

## 4. Adaptation rules (spec §19)

Triggers come from conversation (memory writer detects them), reassessment, or progress.

| Trigger | Rule |
|---|---|
| "I only have 2 hours a day" (`time_budget`) | rescale schedule; keep critical-path order; drop/defer optional nodes; never silently drop exam-critical ones — say what moved |
| "Maths is difficult for me" (`difficulty`) + low maths score | insert `module:maths_foundation_*` before nodes with `related_subject: mathematics` |
| "I no longer want AI, I like cybersecurity" (`interest_change`) | add `exploration_branch` for cybersecurity; AI-specific nodes → `parked` (not deleted); shared nodes (Python, maths) stay |
| Reassessment shows skill improved | mark modules satisfied by measurement as `done` with evidence `assessment` |
| Milestone overdue by > 2 windows | suggest (not force) a re-plan in the next session |

Each produces `roadmap_changes` rows with `reason`, and a `ROADMAP_UPDATED` event. MAYA
explains the diff in the session: *"I've added a maths foundation module before Python
projects because you said algebra feels hard. Everything you finished is still counted."*

## 5. Progress

- Module progress = mean of child task status, or measured skill level when the module has
  a `done_when` tied to a skill measurement.
- Skill progress (spec §20) comes from `skill_measurements` (assessments, practice papers,
  projects, self-report — each labelled by source; self-report never overrides a measured value).
- Display: initial vs current per skill, plus a sparkline of measurements over time.

## 6. UI (desktop, 800×480)

Vertical stage list (CLASS 10 → CLASS 11 → CLASS 12 → DEGREE → SPECIALISATION → INTERNSHIP →
CAREER), current stage expanded with its modules (✓ / % / ○). Tapping a node opens its
`detail` (why, how, resources as QR codes — existing QR widget), "Ask MAYA about this", and
for done nodes, the evidence. A "What changed" chip shows the latest version's diff.
