"""Questions the career graph answers (docs/design/04-knowledge-graph.md §4), as small queries
over `kg_nodes`/`kg_edges` — recursive CTEs where a question walks several hops. They run the
same on PostgreSQL and SQLite.

    store = GraphStore(db)                       # call ensure_graph(db) once before, see graph()
    store.prerequisite_path(["skill:machine_learning"])   # what to learn first, in order
    store.pathways("career:ai_data")             # common and alternative routes in
    store.open_by_stream("stream:pcb")           # what stays open, what closes, and why
    store.colleges_for("career:ai_data", state="Madhya Pradesh")   # official programmes only
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import bindparam, select, text
from sqlalchemy.orm import Session

from app.models.knowledge import KgEdge, KgNode

MAX_PREREQUISITE_DEPTH = 4
# College types roughly in the order students ask about them — for listing, never for judging.
COLLEGE_TYPE_ORDER = ["IIT", "NIT", "IIIT", "GFTI", "Medical-Govt", "Medical", "State", "Deemed", "Private"]


def graph(db: Session) -> "GraphStore":
    """The store, with the graph loaded and up to date."""
    from app.knowledge.loader import ensure_graph

    ensure_graph(db)
    return GraphStore(db)


def _view(node: KgNode) -> dict:
    return {"key": node.key, "type": node.type, "name": node.name, "attrs": node.attrs, "source": node.source,
            "review": node.review}


class GraphStore:
    def __init__(self, db: Session):
        self.db = db
        self._nodes: dict[str, dict] = {}
        self._edges: dict[tuple, list[dict]] = {}  # per request: the graph doesn't change mid-request

    # ---------------- basics ----------------

    def node(self, key: str) -> dict | None:
        if key not in self._nodes:
            found = self.db.execute(select(KgNode).where(KgNode.key == key)).scalar_one_or_none()
            if found is None:
                return None
            self._nodes[key] = _view(found)
        return self._nodes[key]

    def nodes(self, keys) -> dict[str, dict]:
        missing = [k for k in set(keys) if k not in self._nodes]
        if missing:
            for found in self.db.execute(select(KgNode).where(KgNode.key.in_(missing))).scalars():
                self._nodes[found.key] = _view(found)
        return {k: self._nodes[k] for k in keys if k in self._nodes}

    def of_type(self, node_type: str) -> list[dict]:
        cache_key = ("type", node_type)
        if cache_key not in self._edges:
            found = self.db.execute(select(KgNode).where(KgNode.type == node_type).order_by(KgNode.key)).scalars().all()
            for n in found:
                self._nodes.setdefault(n.key, _view(n))
            self._edges[cache_key] = [self._nodes[n.key] for n in found]
        return self._edges[cache_key]

    def out(self, key: str, *types: str) -> list[dict]:
        cache_key = ("out", key, types)
        if cache_key not in self._edges:
            query = select(KgEdge).where(KgEdge.src_key == key)
            if types:
                query = query.where(KgEdge.type.in_(types))
            self._edges[cache_key] = [self._edge(e, e.dst_key) for e in self.db.execute(query.order_by(KgEdge.id)).scalars()]
        return self._edges[cache_key]

    def into(self, key: str, *types: str) -> list[dict]:
        cache_key = ("into", key, types)
        if cache_key not in self._edges:
            query = select(KgEdge).where(KgEdge.dst_key == key)
            if types:
                query = query.where(KgEdge.type.in_(types))
            self._edges[cache_key] = [self._edge(e, e.src_key) for e in self.db.execute(query.order_by(KgEdge.id)).scalars()]
        return self._edges[cache_key]

    def _edge(self, edge: KgEdge, other: str) -> dict:
        return {"type": edge.type, "src": edge.src_key, "dst": edge.dst_key, "other": other, "attrs": edge.attrs,
                "weight": edge.weight, "source": edge.source, "review": edge.review}

    def names(self, keys) -> dict[str, dict]:
        return {k: n["name"] for k, n in self.nodes(keys).items()}

    # ---------------- skills ----------------

    def prerequisite_path(self, skills: list[str], max_depth: int = MAX_PREREQUISITE_DEPTH) -> list[dict]:
        """Every skill needed for `skills`, foundations first: each skill comes after everything it
        builds on. [{key, name, depth (0 = asked for), needs: [keys]}]."""
        if not skills:
            return []
        closure = self.db.execute(text("""
            WITH RECURSIVE need(key, depth) AS (
                SELECT dst_key, 1 FROM kg_edges WHERE type = 'skill_prerequisite' AND src_key IN :keys
                UNION
                SELECT e.dst_key, n.depth + 1 FROM kg_edges e JOIN need n ON e.src_key = n.key
                WHERE e.type = 'skill_prerequisite' AND n.depth < :max
            )
            SELECT key, MIN(depth) FROM need GROUP BY key
        """).bindparams(bindparam("keys", expanding=True)), {"keys": list(skills), "max": max_depth}).all()
        depth = {key: d for key, d in closure}
        depth.update({k: 0 for k in skills})
        keys = list(depth)
        needs: dict[str, list[str]] = defaultdict(list)
        for src, dst in self.db.execute(
                select(KgEdge.src_key, KgEdge.dst_key)
                .where(KgEdge.type == "skill_prerequisite", KgEdge.src_key.in_(keys), KgEdge.dst_key.in_(keys))).all():
            needs[src].append(dst)
        names = self.names(keys)
        # Foundations first (Kahn's order); ties by depth (deeper = more basic) then name.
        ordered, placed = [], set()
        remaining = set(keys)
        while remaining:
            ready = sorted((k for k in remaining if all(n in placed for n in needs[k])),
                           key=lambda k: (-depth[k], names.get(k, {}).get("en", k)))
            if not ready:  # a cycle can't reach here (the loader refuses them); stop rather than loop
                ready = sorted(remaining)
            for k in ready:
                ordered.append({"key": k, "name": names.get(k, {"en": k, "hi": k}), "depth": depth[k],
                                "needs": sorted(needs[k])})
                placed.add(k)
                remaining.discard(k)
        return ordered

    def developed_by(self, skill: str) -> list[dict]:
        found = self.out(skill, "developed_by")
        nodes = self.nodes([e["other"] for e in found])
        return [{"key": e["other"], "type": nodes[e["other"]]["type"], "name": nodes[e["other"]]["name"],
                 "attrs": nodes[e["other"]]["attrs"]} for e in found if e["other"] in nodes]

    def skills_for(self, career: str) -> list[dict]:
        found = self.out(career, "requires_skill")
        nodes = self.nodes([e["other"] for e in found])
        rows = [{"key": e["other"], "name": nodes[e["other"]]["name"], "level": e["attrs"].get("level"),
                 "importance": e["attrs"].get("importance", 0.5),
                 "measured_by": nodes[e["other"]]["attrs"].get("measured_by", []), "review": e["review"]}
                for e in found if e["other"] in nodes]
        return sorted(rows, key=lambda r: -r["importance"])

    # ---------------- routes ----------------

    def degree_requirements(self, degree: str) -> dict:
        """{"mandatory": [...], "one_of": {group: [...]}, "recommended": [{key, note}]} — subject keys."""
        req = {"mandatory": [], "one_of": defaultdict(list), "recommended": []}
        for e in self.out(degree, "requires_subject"):
            if e["attrs"].get("mandatory"):
                req["mandatory"].append(e["other"])
            elif e["attrs"].get("one_of"):
                req["one_of"][e["attrs"]["one_of"]].append(e["other"])
            else:
                req["recommended"].append({"key": e["other"], "note": e["attrs"].get("note")})
        req["one_of"] = dict(req["one_of"])
        return req

    def _route(self, career: str, edge: dict) -> dict:
        degree = edge["other"]
        node = self.node(degree)
        req = self.degree_requirements(degree)
        exams = self.out(degree, "requires_exam")
        followed_by = self.out(degree, "continues_to")
        subject_keys = req["mandatory"] + [k for g in req["one_of"].values() for k in g] + [r["key"] for r in req["recommended"]]
        names = self.names(subject_keys + [e["other"] for e in exams] + [e["other"] for e in followed_by])
        offered = self.db.execute(select(KgEdge.attrs).where(KgEdge.src_key == degree, KgEdge.type == "offered_at")).scalars().all()
        return {
            "degree": {"key": degree, "name": node["name"], "level": node["attrs"].get("level"),
                       "duration_years": node["attrs"].get("duration_years"), "note": node["attrs"].get("note")},
            "commonness": edge["attrs"].get("commonness", "common"), "note": edge["attrs"].get("note"),
            "subjects": {"mandatory": [{"key": k, "name": names[k]} for k in req["mandatory"]],
                         "one_of": [[{"key": k, "name": names[k]} for k in g] for g in req["one_of"].values()],
                         "recommended": [{"key": r["key"], "name": names[r["key"]], "note": r["note"]}
                                         for r in req["recommended"]]},
            "streams": [s for s in self.streams_open_for(degree)],
            "exams": [{"key": e["other"], "name": names[e["other"]], "note": e["attrs"].get("note"),
                       "url": (self.node(e["other"]) or {}).get("source", {}).get("url")} for e in exams],
            "then": [{"key": e["other"], "name": names[e["other"]]} for e in followed_by],
            "colleges_on_record": len(offered),
            "programmes_on_record": sum(len(a.get("programmes", [])) for a in offered),
            "review": edge["review"],
        }

    def pathways(self, career: str) -> dict:
        """{"common": [route], "alternative": [route], "career_exams": [...]} — each route: the
        degree, the class 11-12 subjects it needs, which streams lead there, the entrance exams,
        what can follow, and how many official programmes the Pi knows of."""
        routes = {"common": [], "alternative": []}
        for edge in self.out(career, "entered_through"):
            route = self._route(career, edge)
            routes["common" if route["commonness"] == "common" else "alternative"].append(route)
        own_exams = self.out(career, "requires_exam")
        names = self.names([e["other"] for e in own_exams])
        routes["career_exams"] = [{"key": e["other"], "name": names[e["other"]],
                                   "url": (self.node(e["other"]) or {}).get("source", {}).get("url")} for e in own_exams]
        return routes

    # ---------------- streams ----------------

    def _stream_subjects(self, stream: str) -> tuple[set[str], set[str]]:
        core, optional = set(), set()
        for e in self.out(stream, "stream_includes"):
            (optional if e["attrs"].get("optional") else core).add(e["other"])
        return core, optional

    def _fits(self, req: dict, subjects: set[str]) -> bool:
        return set(req["mandatory"]) <= subjects and all(set(group) & subjects for group in req["one_of"].values())

    def streams_open_for(self, degree: str) -> list[dict]:
        req = self.degree_requirements(degree)
        out = []
        for stream in self.of_type("stream"):
            core, optional = self._stream_subjects(stream["key"])
            if self._fits(req, core):
                out.append({"key": stream["key"], "name": stream["name"], "if_you_add": []})
            elif self._fits(req, core | optional):
                needed = sorted((set(req["mandatory"]) - core)
                                | {s for g in req["one_of"].values() if not set(g) & core for s in set(g) & optional})
                out.append({"key": stream["key"], "name": stream["name"], "if_you_add": needed})
        return out

    def open_by_stream(self, stream: str) -> dict:
        """For one stream: every career, whether it stays open (by its best route), opens only if
        you add an optional subject, or closes — with the degree and the subjects that decide it."""
        core, optional = self._stream_subjects(stream)
        careers = {"open": [], "if_you_add": [], "closed": []}
        names = {}
        for career in self.of_type("career"):
            best = None
            for edge in self.out(career["key"], "entered_through"):
                degree = self.node(edge["other"])
                if degree is None or degree["attrs"].get("level") == "PG":
                    continue  # a postgraduate route follows another degree, not a stream
                req = self.degree_requirements(degree["key"])
                rank = (0 if self._fits(req, core) else 1 if self._fits(req, core | optional) else 2,
                        0 if edge["attrs"].get("commonness") == "common" else 1)
                missing = sorted((set(req["mandatory"]) | {s for g in req["one_of"].values() for s in g if not set(g) & core})
                                 - core)
                notes = [r for r in req["recommended"] if r["key"] not in core and r.get("note")]
                if best is None or rank < best[0]:
                    best = (rank, degree, missing, notes)
            if best is None:
                continue
            (status, _common), degree, missing, notes = best
            names.update({k: None for k in missing + [n["key"] for n in notes]})
            careers[("open", "if_you_add", "closed")[status]].append({
                "career": {"key": career["key"], "name": career["name"]},
                "via": {"key": degree["key"], "name": degree["name"]},
                "missing": missing, "notes": notes})
        subject_names = self.names(list(names))
        for bucket in careers.values():
            for row in bucket:
                row["missing"] = [{"key": k, "name": subject_names.get(k, {"en": k, "hi": k})} for k in row["missing"]]
                row["notes"] = [{"key": n["key"], "name": subject_names.get(n["key"], {"en": n["key"], "hi": n["key"]}),
                                 "note": n["note"]} for n in row["notes"]]
        node = self.node(stream)
        return {"stream": {"key": stream, "name": node["name"] if node else {"en": stream, "hi": stream}},
                "subjects": sorted(core), "optional_subjects": sorted(optional), **careers}

    # ---------------- careers ----------------

    def related(self, career: str, limit: int = 5) -> list[dict]:
        """Careers named as related, then careers that share many of the same skills."""
        out: dict[str, dict] = {}
        for e in self.out(career, "related_career") + self.into(career, "related_career"):
            out.setdefault(e["other"], {"key": e["other"], "via": "related", "shared_skills": []})
        mine = {e["other"] for e in self.out(career, "requires_skill")}
        rows = self.db.execute(select(KgEdge.src_key, KgEdge.dst_key)
                               .where(KgEdge.type == "requires_skill", KgEdge.src_key != career,
                                      KgEdge.src_key.like("career:%"))).all()
        theirs: dict[str, set[str]] = defaultdict(set)
        for src, dst in rows:
            theirs[src].add(dst)
        for other, skills in theirs.items():
            shared = mine & skills
            jaccard = len(shared) / len(mine | skills) if mine | skills else 0
            if jaccard >= 0.25:
                entry = out.setdefault(other, {"key": other, "via": "shared skills", "shared_skills": []})
                entry["shared_skills"] = sorted(shared)
                entry["overlap"] = round(jaccard, 2)
        names = self.names(list(out) + [s for r in out.values() for s in r["shared_skills"]])
        rows = sorted(out.values(), key=lambda r: (r["via"] != "related", -r.get("overlap", 0), r["key"]))[:limit]
        return [{**r, "name": names.get(r["key"]), "shared_skills": [{"key": s, "name": names[s]} for s in r["shared_skills"]]}
                for r in rows if r["key"] in names]

    def domain_of(self, career: str) -> dict | None:
        for e in self.out(career, "part_of"):
            if e["attrs"].get("primary", True):
                node = self.node(e["other"])
                return {"key": node["key"], "name": node["name"], "order": node["attrs"].get("order", 99)}
        return None

    def domain_tree(self) -> list[dict]:
        """Spec §11's exploration tree: each domain with its careers (a career can be in two)."""
        domains = sorted(self.of_type("domain"), key=lambda d: d["attrs"].get("order", 99))
        tree = []
        for domain in domains:
            members = self.into(domain["key"], "part_of")
            names = self.names([e["other"] for e in members])
            careers = sorted(({"key": e["other"], "name": names[e["other"]], "primary": e["attrs"].get("primary", True)}
                              for e in members if e["other"] in names), key=lambda c: c["name"]["en"])
            tree.append({"key": domain["key"], "name": domain["name"], "careers": careers})
        return tree

    # ---------------- colleges (official programmes only) ----------------

    def college_counts(self, career: str, state: str | None = None) -> dict:
        """How many colleges have an official programme on a route into this career — in all, and
        in one state. Cheap: the whole offered_at list is read once per request."""
        if "offered" not in self._edges:
            rows = self.db.execute(select(KgEdge.src_key, KgEdge.dst_key).where(KgEdge.type == "offered_at")).all()
            self._edges["offered"] = rows
            self.nodes({dst for _src, dst in rows})
        degrees = {e["other"] for e in self.out(career, "entered_through")}
        colleges = {dst for src, dst in self._edges["offered"] if src in degrees}
        in_state = None
        if state:
            in_state = sum(1 for c in colleges if (self._nodes[c]["attrs"].get("state") or "").lower() == state.lower())
        return {"total": len(colleges), "in_state": in_state, "state": state}

    def colleges_for(self, key: str, state: str | None = None, city: str | None = None, limit: int = 25) -> dict:
        """Colleges with an official 2026 programme on a route into `key` (a career or a degree),
        optionally in one state/city. Facts like fees and facilities aren't here — Phase 6."""
        if key.startswith("career:"):
            routes = sorted(self.out(key, "entered_through"), key=lambda e: e["attrs"].get("commonness") != "common")
            degrees = [e["other"] for e in routes]
        else:
            degrees = [key]
        offered = self.db.execute(select(KgEdge).where(KgEdge.type == "offered_at", KgEdge.src_key.in_(degrees))).scalars().all()
        colleges = self.nodes([e.dst_key for e in offered])
        degree_names = self.names(degrees)
        by_college: dict[str, dict] = {}
        for e in offered:
            college = colleges.get(e.dst_key)
            if college is None:
                continue
            a = college["attrs"]
            if state and (a.get("state") or "").lower() != state.lower():
                continue
            if city and (a.get("city") or "").lower() != city.lower():
                continue
            entry = by_college.setdefault(college["key"], {
                "key": college["key"], "college_id": a.get("college_id"), "name": college["name"]["en"],
                "city": a.get("city"), "state": a.get("state"), "type": a.get("college_type"),
                "ownership": a.get("ownership"), "website": a.get("website"), "programmes": [], "sources": []})
            for p in e.attrs.get("programmes", []):
                entry["programmes"].append({**p, "degree": e.src_key, "degree_name": degree_names.get(e.src_key)})
            source = {k: e.source.get(k) for k in ("ref", "academic_year", "url") if e.source.get(k)}
            if source not in entry["sources"]:
                entry["sources"].append(source)

        def order(c):
            kind = c["type"] or ""
            rank = next((n for n, t in enumerate(COLLEGE_TYPE_ORDER) if kind.startswith(t)), len(COLLEGE_TYPE_ORDER))
            return (rank, c["name"])

        found = sorted(by_college.values(), key=order)
        return {"total": len(found), "colleges": found[:limit], "degrees": degrees,
                "not_included": "fees, hostels, facilities and distances — not yet collected from official sources"}
