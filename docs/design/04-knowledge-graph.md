# 04 — Career knowledge graph (Phase 4)

## 1. Storage

Two tables in Postgres (`kg_nodes`, `kg_edges`, doc 02 §7) behind the `GraphStore`
interface. Node keys are stable typed slugs (`career:ai_ml_engineer`, `skill:python`,
`degree:btech_cse`), used everywhere else (interests, assessment dimensions, roadmap
`kg_refs`) so other modules reference the graph without foreign-key coupling.

Why not Neo4j: expected size is a few thousand nodes and tens of thousands of edges; every
query below is a 1–4 hop traversal that a recursive CTE answers in milliseconds. If that
stops being true, a Neo4j `GraphStore` can replace the Postgres one without caller changes.

## 2. Node types

| Type | Key example | Key attrs |
|---|---|---|
| `career` | `career:ai_ml_engineer` | summary, work_style, typical_entry_age, outlook_note + source |
| `job_role` | `role:data_analyst` | seniority, sectors |
| `industry` | `industry:healthcare` | |
| `domain` | `domain:technology` | groups careers for exploration trees (spec §11) |
| `skill` | `skill:python` | kind (`technical`\|`cognitive`\|`soft`), levels `[foundation, intermediate, advanced]` |
| `subject` | `subject:mathematics` | school_level (`secondary`\|`senior_secondary`) |
| `stream` | `stream:PCM` | |
| `degree` | `degree:btech_cse` | level (`UG`\|`PG`\|`diploma`), duration_years |
| `course` | `course:ncert_physics_11` | provider, free/paid |
| `exam` | `exam:JEE_MAIN` | links to existing `exams` row |
| `program` | `program:iitb_btech_cse` | the specific college offering (links to `college_courses`) |
| `college` / `university` | `college:1234` | links to `colleges` row; attrs live in `facts` |
| `certification` | `cert:aws_ccp` | |
| `project` | `project:line_follower_robot` | difficulty, est_hours, skills developed |
| `location` | `city:pune`, `state:MH` | lat/lng |
| `trait` | `trait:investigative` | RIASEC-style dimensions used by assessments |

## 3. Edge types

| Edge | From → To | Attrs |
|---|---|---|
| `requires_skill` | career/role/degree → skill | level, importance 0–1 |
| `skill_prerequisite` | skill → skill | |
| `developed_by` | skill → project/course/certification | level reached |
| `related_subject` | career/degree/skill → subject | strength |
| `stream_includes` | stream → subject | |
| `entered_through` | career → degree | commonness (`common`\|`alternative`\|`rare`) |
| `requires_subject` | degree → subject | at school level, mandatory bool |
| `requires_exam` | degree/program → exam | |
| `offered_by` | degree → program; program → college | |
| `part_of` | college → university; career → domain; role → industry | |
| `leads_to_role` | career → job_role | |
| `related_career` | career ↔ career | similarity, transition_note |
| `located_in` | college → city; city → state | |
| `near` | college → place (hospital, station, airport) | distance_km, travel_min, **fact_id** (provenance) |
| `fits_trait` | career → trait | weight (from today's `career_options.profile`) |

Facts that change (fees, facilities, distances) are **not** graph attributes — the edge
points at a `facts` row (doc 06) so freshness and source travel with the value.

## 4. Query patterns

| Question | Traversal |
|---|---|
| "What do I need to become an AI engineer?" | `career:ai_ml_engineer` -requires_skill→ skills, then -skill_prerequisite*→ (recursive, depth ≤ 4) ⇒ ordered learning path |
| "How do people get into it?" | career -entered_through→ degree -requires_subject→ subject; degree -requires_exam→ exam |
| "Which colleges near me offer it?" | career → degree -offered_by→ program -offered_by→ college -located_in→ city, then filter by distance with `facts` (lat/lng) |
| "What else is like this?" | career -related_career→ career; or shared `requires_skill` overlap (Jaccard) |
| "If I take PCB, what stays open?" | stream:PCB -stream_includes→ subjects ← requires_subject- degree ← entered_through- careers |
| Exploration tree (spec §11) | domain ← part_of- careers |

```sql
-- prerequisite closure for a career's skills
WITH RECURSIVE need(key, depth) AS (
  SELECT dst_key, 1 FROM kg_edges WHERE src_key = 'career:ai_ml_engineer' AND type = 'requires_skill'
  UNION
  SELECT e.dst_key, n.depth + 1 FROM kg_edges e JOIN need n ON e.src_key = n.key
  WHERE e.type = 'skill_prerequisite' AND n.depth < 4
)
SELECT DISTINCT key, min(depth) FROM need GROUP BY key ORDER BY 2 DESC;
```

## 5. How the graph is used by other modules

- **Career engine**: alignment = f(assessment dimension scores, `fits_trait` weights,
  `requires_skill` vs. measured skills, interests, constraints). Output per career: why it
  may fit (which edges matched which scores), skill gaps (required skills below level),
  pathways (`entered_through` common + alternative), things to explore (projects via
  `developed_by`). Never one opaque score.
- **Roadmap**: modules reference skill/subject/project nodes; prerequisite edges give ordering.
- **College discovery**: the path career → degree → program → college bounds the search.
- **Memory**: interests and memory items carry `node_key`, enabling "everything about Python".

## 6. Where the content comes from

1. Bootstrap from what exists: `seed/careers.json` (careers, subjects, exams, skills,
   related careers, trait profile) and `seed/syllabus.json` (subjects, chapters).
2. Curated YAML in `apps/api/app/seed/graph/*.yaml`, reviewed like code, each node/edge with
   a `source` (e.g. NCS career pages, NCERT, official exam bulletins, AICTE/NMC/UGC listings).
3. Programs and colleges are generated from official data (JoSAA/MCC files today, more in P6),
   never hand-typed.
A validation script fails CI on dangling keys, cycles in `skill_prerequisite`, or careers
with no `entered_through` edge.
