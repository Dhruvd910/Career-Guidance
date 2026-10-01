"""Building the career knowledge graph and loading it — whole, validated, versioned.

The pipeline of spec §14: sources → extraction → validation → normalisation → canonical model →
graph. Three inputs make one snapshot:

1. **Curated knowledge**, the canonical YAML in app/knowledge/graph/: skills and their
   prerequisites, degrees and what they require, exams with their official sites, careers and
   their routes. Written by an editor (so far Claude), so marked "unreviewed" until a person
   signs it off.
2. **The career library**, app/seed/careers.json. It supplies RIASEC traits, subjects, related
   careers, and the roles and sectors from each guide. These are taken over, not copied.
3. **Official data already on the Pi**, the JoSAA/MCC 2026 programmes. Colleges, cities and
   states come from it, and so does `degree -offered_at-> college`, using each degree's
   programme-name patterns. A programme no pattern matches is reported, never guessed.

The snapshot is validated (dangling keys, edge types, prerequisite cycles, careers without a
route, degrees without subject requirements, library and graph out of step) and swapped in within
one transaction, only when its inputs changed. `kg_versions` keeps each load's counts and what
didn't match.

    python -m app.knowledge.loader            # load (if anything changed) and print a summary
    python -m app.knowledge.loader --export   # print the canonical snapshot as JSON
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.knowledge.spec import EDGE_TYPES, NODE_TYPES, GraphFile, Source
from app.models.college import Branch, College, CollegeCourse, Course
from app.models.exam import Exam
from app.models.knowledge import KgEdge, KgNode, KgVersion

GRAPH_DIR = Path(__file__).parent / "graph"
LIBRARY = Path(__file__).resolve().parent.parent / "seed" / "careers.json"
FROM_LIBRARY = Source(kind="derived", ref="careers.json")
RIASEC = ("realistic", "investigative", "artistic", "social", "enterprising", "conventional")
# Assessment interest dimensions → school subjects (a career's profile weight ≥ 2 makes a link).
PROFILE_SUBJECTS = {
    "maths": ["mathematics"], "physics": ["physics"], "chemistry": ["chemistry"], "biology": ["biology"],
    "computer": ["computer_science"], "commerce": ["accountancy", "business_studies"], "arts": ["fine_arts"],
    "language": ["english"], "society": ["political_science", "history"],
}

_lock = threading.Lock()


class GraphInvalid(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__(f"{len(problems)} problem(s) in the knowledge graph:\n- " + "\n- ".join(problems[:40]))
        self.problems = problems


@dataclass
class Snapshot:
    nodes: dict[str, dict] = field(default_factory=dict)
    edges: dict[tuple[str, str, str], dict] = field(default_factory=dict)
    unmatched: dict = field(default_factory=dict)

    def node(self, key: str, name: dict, source: Source, attrs: dict | None = None, aliases=()) -> None:
        if key in self.nodes:
            self.nodes[key]["attrs"].update(attrs or {})
            return
        self.nodes[key] = {"key": key, "type": key.split(":", 1)[0], "name": dict(name), "aliases": list(aliases),
                           "attrs": dict(attrs or {}), "source": source.model_dump(exclude_none=True),
                           "review": source.review}

    def edge(self, src: str, edge_type: str, dst: str, source: Source, attrs: dict | None = None,
             weight: float | None = None) -> None:
        key = (src, edge_type, dst)
        if key in self.edges:  # the same fact twice: keep the first, add any new detail
            self.edges[key]["attrs"].update(attrs or {})
            return
        self.edges[key] = {"src_key": src, "type": edge_type, "dst_key": dst, "attrs": dict(attrs or {}),
                           "weight": weight, "source": source.model_dump(exclude_none=True), "review": source.review}

    def canonical(self) -> dict:
        return {"nodes": [self.nodes[k] for k in sorted(self.nodes)],
                "edges": [self.edges[k] for k in sorted(self.edges)]}


def slug(text: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text.lower())).strip("_")


# ---------------- inputs ----------------

def _files(graph_dir: Path) -> list[Path]:
    return sorted(graph_dir.glob("*.yaml"))


def _files_sha(graph_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in [*_files(graph_dir), LIBRARY]:
        digest.update(path.name.encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


@lru_cache(maxsize=4)
def _parsed(graph_dir: str, sha: str) -> list[GraphFile]:
    files = []
    for path in _files(Path(graph_dir)):
        try:
            files.append(GraphFile.model_validate(yaml.safe_load(path.read_text())))
        except Exception as e:  # noqa: BLE001 — name the file in the message
            raise GraphInvalid([f"{path.name}: {e}"]) from e
    return files


def _library() -> list[dict]:
    return json.loads(LIBRARY.read_text())["careers"]


def official_signature(db: Session) -> list:
    """Changes whenever the official tables the graph is built from change."""
    return [
        db.execute(select(func.count(), func.max(College.id)).where(College.is_demo_data.is_(False))).one(),
        db.execute(select(func.count(), func.max(CollegeCourse.id))
                   .where(CollegeCourse.verification_status == "verified")).one(),
        db.execute(select(func.count(), func.max(Branch.id))).one(),
    ]


def inputs_fingerprint(db: Session, graph_dir: Path = GRAPH_DIR) -> str:
    sig = json.dumps([list(row) for row in official_signature(db)], default=str)
    return hashlib.sha256((_files_sha(graph_dir) + sig).encode()).hexdigest()


# ---------------- building the snapshot ----------------

def _curated(snap: Snapshot, files: list[GraphFile]) -> None:
    for graph_file in files:
        for node in graph_file.nodes:
            source = node.source or graph_file.source
            snap.node(node.key, node.name.model_dump(), source, node.attrs, node.aliases)
            for edge_type, targets in node.edges.items():
                for n, target in enumerate(targets):
                    attrs = dict(target.attrs)
                    if edge_type == "part_of":
                        attrs["primary"] = n == 0  # a career's first domain is its main one
                    snap.edge(node.key, edge_type, target.to, target.source or source, attrs, target.weight)


def _from_library(snap: Snapshot, library: list[dict]) -> None:
    for career in library:
        key = f"career:{career['key']}"
        if key not in snap.nodes:
            continue  # reported by validation: every library career needs its curated node
        snap.nodes[key]["attrs"].update({"library_key": career["key"], "summary": career.get("description", ""),
                                         "category": career.get("category", "")})
        profile = career.get("profile") or {}
        for dim in RIASEC:
            if profile.get(dim):
                snap.edge(key, "fits_trait", f"trait:{dim}", FROM_LIBRARY, weight=round(profile[dim] / 3, 3))
        for dim, subjects in PROFILE_SUBJECTS.items():
            if profile.get(dim, 0) >= 2:
                for subject in subjects:
                    snap.edge(key, "related_subject", f"subject:{subject}", FROM_LIBRARY,
                              {"strength": round(profile[dim] / 3, 3)})
        for other in career.get("related", []):
            snap.edge(key, "related_career", f"career:{other}", FROM_LIBRARY)
        details = career.get("details") or {}
        for role in details.get("roles", []):
            role_key = f"job_role:{slug(role)}"
            snap.node(role_key, {"en": role, "hi": role}, FROM_LIBRARY)
            snap.edge(key, "leads_to_role", role_key, FROM_LIBRARY)
        for sector in details.get("sectors", []):
            industry_key = f"industry:{slug(sector)}"
            snap.node(industry_key, {"en": sector, "hi": sector}, FROM_LIBRARY)
            snap.edge(key, "works_in", industry_key, FROM_LIBRARY)


def _programme_matcher(snap: Snapshot):
    """Degree nodes say which official programmes are theirs: [{course: regex, branch: regex}].
    Checked in `match_order` (specific before general), first match wins."""
    rules = []
    for key, node in snap.nodes.items():
        for rule in node["attrs"].get("programmes", []) if node["type"] == "degree" else []:
            rules.append((node["attrs"].get("match_order", 100), key, re.compile(rule["course"], re.I),
                          re.compile(rule["branch"], re.I) if rule.get("branch") else None,
                          re.compile(rule["except"], re.I) if rule.get("except") else None))
    rules.sort(key=lambda r: (r[0], r[1]))

    def match(course: str, branch: str | None) -> str | None:
        for _order, key, course_re, branch_re, except_re in rules:
            if not course_re.search(course):
                continue
            if branch_re is not None and not (branch and branch_re.search(branch)):
                continue
            if except_re is not None and branch and except_re.search(branch):
                continue
            return key
        return None

    return match


def _official(snap: Snapshot, db: Session) -> None:
    colleges = db.execute(select(College).where(College.is_demo_data.is_(False))).scalars().all()
    official_colleges = Source(kind="official", ref="josaa_mcc_2026_institutes")
    for college in colleges:
        state_key, city_key = f"state:{slug(college.state)}", f"city:{slug(college.city)}_{slug(college.state)}"
        snap.node(state_key, {"en": college.state, "hi": college.state}, official_colleges)
        snap.node(city_key, {"en": college.city, "hi": college.city}, official_colleges, {"state": college.state})
        snap.edge(city_key, "located_in", state_key, official_colleges)
        key = f"college:{college.id}"
        snap.node(key, {"en": college.canonical_name, "hi": college.canonical_name}, official_colleges, {
            "college_id": college.id, "college_type": college.college_type, "ownership": college.ownership,
            "city": college.city, "state": college.state, "website": college.official_website,
        }, college.aliases or [])
        snap.edge(key, "located_in", city_key, official_colleges)

    match = _programme_matcher(snap)
    rows = db.execute(
        select(CollegeCourse.id, CollegeCourse.college_id, CollegeCourse.source, CollegeCourse.source_url,
               CollegeCourse.academic_year, Course.name, Branch.name, Exam.code)
        .join(Course, Course.id == CollegeCourse.course_id)
        .outerjoin(Branch, Branch.id == CollegeCourse.branch_id)
        .join(Exam, Exam.id == CollegeCourse.exam_id)
        .where(CollegeCourse.verification_status == "verified")).all()
    unmatched: Counter = Counter()
    for cc_id, college_id, source_name, source_url, year, course, branch, exam in rows:
        if f"college:{college_id}" not in snap.nodes:
            continue
        degree = match(course, branch)
        if degree is None:
            unmatched[f"{course} | {branch}" if branch else course] += 1
            continue
        source = Source(kind="official", ref=source_name or "official", url=source_url, academic_year=year)
        key = (degree, "offered_at", f"college:{college_id}")
        snap.edge(*key, source)
        programmes = snap.edges[key]["attrs"].setdefault("programmes", [])
        programmes.append({"college_course_id": cc_id, "course": course, "branch": branch, "exam": exam})
    snap.unmatched = {"programmes": sum(unmatched.values()),
                      "names": [{"name": n, "count": c} for n, c in unmatched.most_common()]}


def validate(snap: Snapshot, library: list[dict] | None = None, measures: set[str] | None = None) -> None:
    problems = []
    for key, node in snap.nodes.items():
        if node["type"] not in NODE_TYPES:
            problems.append(f"{key}: unknown node type '{node['type']}'")
    for (src, edge_type, dst) in snap.edges:
        if edge_type not in EDGE_TYPES:
            problems.append(f"{src} -{edge_type}-> {dst}: unknown edge type")
            continue
        for end, allowed in ((src, EDGE_TYPES[edge_type][0]), (dst, EDGE_TYPES[edge_type][1])):
            if end not in snap.nodes:
                problems.append(f"{src} -{edge_type}-> {dst}: '{end}' doesn't exist")
            elif snap.nodes[end]["type"] not in allowed:
                problems.append(f"{src} -{edge_type}-> {dst}: '{end}' can't be on that end of {edge_type}")
    out: dict[str, set[str]] = defaultdict(set)
    for (src, edge_type, dst) in snap.edges:
        out[f"{src}|{edge_type}"].add(dst)
    for key, node in snap.nodes.items():
        if node["type"] == "career":
            for needed in ("entered_through", "part_of", "requires_skill"):
                if not out.get(f"{key}|{needed}"):
                    problems.append(f"{key}: no {needed} edge")
        # A postgraduate degree follows another degree, not class 12 subjects.
        if node["type"] == "degree" and node["attrs"].get("level") != "PG" and not out.get(f"{key}|requires_subject"):
            problems.append(f"{key}: no requires_subject edge")
        for measure in node["attrs"].get("measured_by", []) if measures is not None else []:
            if measure not in measures:
                problems.append(f"{key}: measured_by '{measure}' isn't an assessment dimension")
    problems += _cycles(snap)
    if library is not None:
        library_keys = {f"career:{c['key']}" for c in library}
        graph_keys = {k for k, n in snap.nodes.items() if n["type"] == "career"}
        problems += [f"{k}: in careers.json but not in the graph" for k in sorted(library_keys - graph_keys)]
        problems += [f"{k}: in the graph but not in careers.json" for k in sorted(graph_keys - library_keys)]
    if problems:
        raise GraphInvalid(problems)


def _cycles(snap: Snapshot) -> list[str]:
    needs: dict[str, list[str]] = defaultdict(list)
    for (src, edge_type, dst) in snap.edges:
        if edge_type == "skill_prerequisite":
            needs[src].append(dst)
    problems, state = [], {}

    def visit(key: str, trail: list[str]) -> None:
        state[key] = "visiting"
        for nxt in needs.get(key, []):
            if state.get(nxt) == "visiting":
                problems.append("prerequisite cycle: " + " → ".join(trail[trail.index(nxt):] + [nxt]))
            elif nxt not in state:
                visit(nxt, trail + [nxt])
        state[key] = "done"

    for key in list(needs):
        if key not in state:
            visit(key, [key])
    return problems


def build(db: Session, graph_dir: Path = GRAPH_DIR, library: list[dict] | None = None) -> Snapshot:
    from app.assessment.alignment import dimension_labels

    snap = Snapshot()
    _curated(snap, _parsed(str(graph_dir), _files_sha(graph_dir)))
    library = _library() if library is None else library
    _from_library(snap, library)
    _official(snap, db)
    validate(snap, library, set(dimension_labels()))
    return snap


# ---------------- loading ----------------

def current_version(db: Session) -> KgVersion | None:
    return db.execute(select(KgVersion).order_by(KgVersion.id.desc()).limit(1)).scalar_one_or_none()


def load(db: Session, snap: Snapshot, fingerprint: str) -> KgVersion:
    """Swaps the graph for this snapshot in one transaction."""
    db.execute(delete(KgEdge))
    db.execute(delete(KgNode))
    if snap.nodes:
        db.execute(insert(KgNode), list(snap.nodes.values()))
    if snap.edges:
        db.execute(insert(KgEdge), list(snap.edges.values()))
    counts = {"nodes": dict(Counter(n["type"] for n in snap.nodes.values())),
              "edges": dict(Counter(e["type"] for e in snap.edges.values())),
              "review": dict(Counter(e["review"] for e in snap.edges.values()))}
    version = KgVersion(fingerprint=fingerprint, counts=counts, unmatched=snap.unmatched,
                        nodes=len(snap.nodes), edges=len(snap.edges))
    db.add(version)
    db.commit()
    return version


def ensure_graph(db: Session, graph_dir: Path = GRAPH_DIR) -> KgVersion:
    """The graph as of its current inputs — loaded now if they changed since the last load.
    Two cheap queries when nothing changed."""
    fingerprint = inputs_fingerprint(db, graph_dir)
    version = current_version(db)
    if version is not None and version.fingerprint == fingerprint:
        return version
    with _lock:
        version = current_version(db)
        if version is not None and version.fingerprint == fingerprint:
            return version
        snap = build(db, graph_dir)
        try:
            return load(db, snap, fingerprint)
        except IntegrityError:  # another process loaded the same thing first
            db.rollback()
            return current_version(db)


if __name__ == "__main__":
    from app.core.db import SessionLocal

    with SessionLocal() as session:
        if "--export" in sys.argv:
            print(json.dumps(build(session).canonical(), ensure_ascii=False, indent=1, default=str))
        else:
            v = ensure_graph(session)
            print(f"Graph v{v.id}: {v.nodes} nodes, {v.edges} edges")
            print("  nodes:", ", ".join(f"{k} {n}" for k, n in sorted(v.counts["nodes"].items())))
            print("  edges:", ", ".join(f"{k} {n}" for k, n in sorted(v.counts["edges"].items())))
            print(f"  official programmes not matched to a degree: {v.unmatched.get('programmes', 0)}")
            for row in v.unmatched.get("names", [])[:15]:
                print(f"    {row['count']:>3}  {row['name']}")
