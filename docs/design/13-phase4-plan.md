# 13 — Phase 4 plan: Career engine

Scope (spec §11–12, §13's graph part, §14, §32, §34 Phase 4): a career knowledge model with its
relationships, career matching, and career explanations — on top of Phase 3's assessments and
Phase 2's memory. Graph design: doc 04; schema: doc 02 §7; API: doc 07 §5. College *facts*
(fees, hostels, distances, deadlines) are Phase 6, and roadmaps are Phase 5. This phase links
careers to the colleges that offer them only through the official JoSAA/MCC programme data
already on the Pi.

## What exists, and what changes

| Today | Phase 4 |
|---|---|
| 27 careers in `careers.json`; relations are JSON id lists and free-text skills ("logical thinking") | A **knowledge graph** of careers, skills, subjects, streams, degrees, exams, roles, industries, projects, certifications, domains, colleges and cities, with typed edges, each carrying its source |
| "How to get there" is one sentence (`education_path`) | **Pathways from the graph**: stream → subjects → exam → degree → roles, the common route first, then alternatives |
| Skills are words in a list | **Skills with prerequisites**: "Python needs programming fundamentals", so a skill gap becomes an ordered learning path with projects that build each skill |
| Careers grouped by a category string | **Domains as nodes** (spec §11's tree: Technology → Software Engineering, AI & Data, Cybersecurity, Robotics, Product Design…). A career can sit in two domains |
| Directions (Phase 3) say why a career fits | Add **required education, typical and alternative pathways, skill gaps, things to explore, related careers, colleges that offer it** — spec §11's full list |
| No answer to "If I take PCB, what stays open?" | Computed from the subjects each degree requires — for class 9–10 students choosing a stream |
| MAYA's stated-interest memory isn't linked to careers | Interests she remembers ("robotics") are matched to graph nodes **on the Pi** (the Phase 2 embedding model) and become a reason, with the memory permission only |

## Decisions

| ID | Decision | Why |
|---|---|---|
| P4-1 | **Graph = `kg_nodes` + `kg_edges` in PostgreSQL** behind a `GraphStore`; traversals are recursive CTEs (they also run on SQLite, so tests stay fast) | Doc 04 / D4: a few thousand nodes, 1–4 hop queries; no second database on the Pi |
| P4-2 | **The canonical knowledge model is YAML in the repo** (`app/knowledge/graph/*.yaml`): validated, fingerprinted and loaded as one versioned snapshot | Spec §14: sources → validation → normalised canonical form → graph. Reviewed like code; a load either fully succeeds or changes nothing |
| P4-3 | **Every node and edge says where it came from**: `official` (JoSAA/MCC files, exam bulletins), `curated` (editorial judgement, e.g. "AI engineers need statistics"), or `derived` (computed from other data). Curated content is marked *not yet reviewed by a person* until someone signs it off | Honest provenance. The skill and pathway knowledge here is expert judgement written by Claude, not an official fact |
| P4-4 | **Colleges, cities and programmes are generated from the official data, never hand-typed** (doc 04 §6). Degree nodes carry branch-name patterns; each JoSAA/MCC programme that matches becomes a `degree -offered_at-> college` edge. Unmatched branches are reported, not guessed | Spec §12 "DEGREE offered_by COLLEGE" with real provenance; 1,639 verified programmes are already on the Pi |
| P4-5 | **`careers.json` stays the store for long-form guides** (same slug as `career:<key>`). Its relation fields become edges at load time: `related` → `related_career`, `profile` → `fits_trait` / `related_subject`. The free-text `skills_required` is replaced by curated `requires_skill` edges | One source per fact: the graph is built from it rather than copied |
| P4-6 | **The career engine adds no new score.** Phase 3's bands stay the matching; the graph adds explanation | The student decides (spec §11); the bands are already explainable and tested |
| P4-7 | **Skill gaps are only claimed where something was measured.** A skill node may say what measures it (`measured_by: [check:programming, skill:programming]`). Otherwise the skill is listed as "needed — not measured yet", never as a gap | Same honesty rule as Phase 3 |
| P4-8 | **New careers: the spec's own examples — Cybersecurity and Robotics & Automation** — with full guides. Adding more is now a YAML entry plus a guide | Keeps this phase about the engine; the content format makes growth cheap |
| P4-9 | Colleges by **state and city only** (no coordinates yet) and **no fees or facilities** — those are Phase 6 facts with their own freshness rules | Never fabricate (spec §14) |

## Graph content (first version)

| Node type | Roughly | From |
|---|---|---|
| domain | 10 | curated |
| career | 29 | `careers.json` + curated YAML |
| job_role, industry | ~90, ~20 | the guides' `roles` and `sectors`, normalised |
| skill | ~55, with prerequisites | curated |
| subject, stream | ~15, 5 | curated (NCERT subject names) |
| degree | ~30, with branch patterns | curated |
| exam | ~20, with official URLs | curated (official sites) |
| project, certification | ~40, ~8 | curated |
| trait | 6 RIASEC | curated |
| college, city, state | 739, ~440, 35 | official (JoSAA 2026, MCC 2026) |

Edges (doc 04 §3):
- **Career:** `requires_skill` (level, importance), `related_subject`, `entered_through` (common / alternative), `leads_to_role`, `part_of` domain, `fits_trait`, `related_career`.
- **Skill:** `skill_prerequisite`, `developed_by` project / certification / course.
- **Degree:** `requires_subject` (mandatory / recommended), `requires_exam`, `offered_at` college (with the programme rows as evidence).
- **Location:** `located_in` college → city → state.
- **Stream:** `stream_includes`.

A validator fails the load (and CI) on any of these:
- a dangling key
- a cycle in `skill_prerequisite`
- a career with no `entered_through`
- a degree with no `requires_subject`
- a career in `careers.json` that isn't in the graph, or the reverse

## Steps

### Step 0 — Schema
- `kg_nodes`: key unique, type, name `{en,hi}`, aliases, attrs, source, review status.
- `kg_edges`: src_key, type, dst_key unique together; attrs, weight, source.
- `kg_versions`: fingerprint, counts, loaded_at, unmatched official rows.

### Step 1 — Canonical format, loader, validator
- **Format.** YAML → pydantic → one in-memory snapshot. Official and derived nodes and edges are added from the database (colleges, programmes) and from `careers.json` (traits, subjects, related careers).
- **Loading.** The whole snapshot is validated, then swapped in within one transaction.
- **Command.** `python -m app.knowledge.loader` (also run at first use when the fingerprint changed). `--export` writes the canonical JSON.

### Step 2 — Content
- Domains, traits, subjects, streams, skills (with prerequisites and `measured_by`), degrees (with branch patterns, required subjects and exams), exams (with official URLs), projects, certifications.
- Careers with their edges.
- The Cybersecurity and Robotics guides in `careers.json`, plus their Phase 3 needs and questions.
- Roles and industries normalised from the guides.

### Step 3 — GraphStore
- `node`, `neighbours(key, types, direction)`
- `prerequisite_path(skills)`: ordered, depth ≤ 4
- `pathways(career)`: common and alternative routes, each as stream → subjects → exams → degree
- `related(career)`: edges plus skill-overlap (Jaccard)
- `domain_tree()`
- `open_by_stream(stream)` / `closed_by_stream(stream)`
- `colleges_for(career | degree, state?, city?)`: official programmes only

All of them are recursive CTEs or simple joins.

### Step 4 — Career engine
- `options(student)`: Phase 3 directions, each enriched with the pieces below.
- **Required education and pathways:** the common route and its alternatives.
- **Skill gaps (P4-7):** each one has a learning path ordered by prerequisites and projects that build it.
- **Related careers, things to explore, and a count of colleges that offer it.**
- **What she remembers:** linked interests appear as "you told MAYA…" (with memory permission).
- `explain(student, career)`: the full picture for one career.
- **Without assessments:** an exploration view, i.e. the domain tree plus anything linked to remembered interests.

### Step 5 — Memory ↔ graph
- **Matching:** interests and memory items are matched to graph nodes by embedding (local e5, with a threshold calibrated like Phase 2's).
- **Stored:** the match goes in `node_key`.
- **Written for new memories:** the Phase 2 writer fills it as it saves.
- **Backfilled for old ones:** a one-off step fills it for interests saved before this phase.

### Step 6 — APIs
- `GET /api/career/options`
- `GET /api/career/{key}`: guide + graph neighbourhood + pathways + skills (with the student's levels when measured)
- `GET /api/career/explore`: the domain tree
- `GET /api/career/stream/{stream}`: what stays open
- `GET /api/career/{key}/colleges?state=&city=`
- `GET /api/skills/{key}/path`

The existing `/api/careers…` catalogue stays.

### Step 7 — MAYA
Tools:
- `career_pathways`
- `career_skills` (with gaps and learning path)
- `related_careers`
- `what_stays_open` (stream)
- `colleges_offering` (official programmes; clearly *not* fees or facilities)

Plus a prompt rule: education routes, prerequisites and colleges come from these tools, never from memory.

### Step 8 — Screens (800×480)
- **Explore careers:** the domain tree.
- **Career guide:** gains *How people get there* (common and alternative routes as steps), *Skills it needs* (your level when measured, a learning path, projects), *Related careers* and *Colleges that offer it* (by state, from JoSAA/MCC, with source).
- **Stream explorer:** for class 9–10 (PCM / PCB / PCMB / commerce / humanities → what's open, what closes).

### Step 9 — Verification
- **Automated tests:**
  - the validator catches each broken case
  - loading is all-or-nothing and changes nothing when the content hasn't changed
  - traversals give the right results on SQLite and Postgres
  - branch matching against the real programme names (coverage reported)
  - "What stays open" is right for each stream
  - gaps only where something was measured
  - nothing ever says "best"
  - provenance is present on every edge
- **Live rehearsal** with the real model on the test database.
- **Hands-on test:** `phase4-test-script.md`.

## Exit criteria

1. "What do I need to become an AI engineer?" gets an ordered skill path (prerequisites first) with projects. "How do people get into it?" gets the common route and at least one alternative. Both come from the graph, with sources.
2. "Agar mujhe AI karna hai toh mere aas paas kaunse colleges hain?" lists colleges in the student's state that offer a matching programme, from the official 2026 data, and says plainly that fees and facilities aren't available yet.
3. "PCB lu toh kya options khule rahenge?" answers from the graph: what stays open and what closes.
4. The career guide and the directions show required education, typical and alternative pathways, skill gaps (only where measured), things to explore and questions to ask yourself — spec §11's full list.
5. Every node and edge has a source; curated knowledge is labelled as not yet reviewed by a person; the load is validated and versioned.
6. All Phase 1–3 tests still pass.
