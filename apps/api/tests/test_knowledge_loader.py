"""The knowledge graph's loader: building from curated YAML, the career library and official
programmes; validating; loading whole, once per change."""

import textwrap

import pytest

from app.knowledge import loader
from app.knowledge.loader import GraphInvalid, Snapshot, build, ensure_graph, validate
from app.knowledge.spec import Source
from app.models.college import Branch, College, CollegeCourse, Course
from app.models.exam import Exam
from app.models.knowledge import KgEdge, KgNode, KgVersion

GRAPH = textwrap.dedent("""
    source: {kind: curated, ref: test_editorial}
    nodes:
      - key: domain:technology
        name: {en: Technology, hi: टेक्नोलॉजी}
      - key: trait:investigative
        name: {en: Investigative, hi: खोजी}
      - key: subject:mathematics
        name: {en: Mathematics, hi: गणित}
      - key: subject:physics
        name: {en: Physics, hi: भौतिकी}
      - key: skill:programming_fundamentals
        name: {en: Programming fundamentals, hi: प्रोग्रामिंग की बुनियाद}
        attrs: {measured_by: [check:programming, skill:programming]}
      - key: skill:python
        name: {en: Python, hi: पाइथन}
        edges:
          skill_prerequisite: [skill:programming_fundamentals]
      - key: exam:JEE_MAIN
        name: {en: JEE Main, hi: जेईई मेन}
        source: {kind: official, ref: NTA, url: "https://jeemain.nta.nic.in"}
      - key: degree:btech_cse
        name: {en: B.Tech in Computer Science, hi: बी.टेक कंप्यूटर साइंस}
        attrs:
          programmes: [{course: "^B\\\\.Tech", branch: "computer"}]
        edges:
          requires_subject: [{to: subject:mathematics, mandatory: true}, {to: subject:physics, mandatory: true}]
          requires_exam: [exam:JEE_MAIN]
      - key: career:cse
        name: {en: Software engineering, hi: सॉफ़्टवेयर इंजीनियरिंग}
        edges:
          part_of: [domain:technology]
          requires_skill: [{to: skill:python, level: intermediate, importance: 0.9}]
          entered_through: [{to: degree:btech_cse, commonness: common}]
""")
LIBRARY = [{"key": "cse", "name": "Computer Science", "category": "Engineering & Technology", "description": "Build software.",
            "profile": {"maths": 3, "investigative": 2}, "related": [],
            "details": {"roles": ["Software engineer"], "sectors": ["Tech companies"]}}]


@pytest.fixture()
def graph_dir(tmp_path, monkeypatch):
    (tmp_path / "graph.yaml").write_text(GRAPH)
    library = tmp_path / "careers.json"
    import json
    library.write_text(json.dumps({"careers": LIBRARY}))
    monkeypatch.setattr(loader, "LIBRARY", library)
    loader._parsed.cache_clear()
    return tmp_path


@pytest.fixture()
def official(db_session):
    exam = Exam(code="JEE_MAIN", name="JEE Main", category="engineering")
    btech = Course(name="B.Tech", level="UG", duration_years=4)
    db_session.add_all([exam, btech])
    db_session.flush()
    cse = Branch(course_id=btech.id, name="Computer Science and Engineering", code="CSE")
    mining = Branch(course_id=btech.id, name="Mining Engineering", code="MIN")
    college = College(canonical_name="National Institute of Technology, Example", college_type="NIT",
                      ownership="government", state="Madhya Pradesh", city="Bhopal", is_demo_data=False)
    db_session.add_all([cse, mining, college])
    db_session.flush()
    for branch in (cse, mining):
        db_session.add(CollegeCourse(college_id=college.id, course_id=btech.id, branch_id=branch.id, exam_id=exam.id,
                                     source="JoSAA opening & closing ranks", academic_year="2026-27",
                                     verification_status="verified"))
    db_session.commit()
    return college


def test_the_graph_is_built_from_all_three_sources(db_session, graph_dir, official):
    version = ensure_graph(db_session, graph_dir)
    keys = {n.key: n for n in db_session.query(KgNode)}
    assert {"career:cse", "skill:python", "college:%d" % official.id, "city:bhopal_madhya_pradesh",
            "state:madhya_pradesh", "job_role:software_engineer", "industry:tech_companies"} <= set(keys)
    assert keys["career:cse"].attrs["library_key"] == "cse" and keys["career:cse"].review == "unreviewed"
    edges = {(e.src_key, e.type, e.dst_key): e for e in db_session.query(KgEdge)}
    offered = edges[("degree:btech_cse", "offered_at", f"college:{official.id}")]
    assert offered.review == "official" and offered.source["academic_year"] == "2026-27"
    assert offered.attrs["programmes"][0]["branch"] == "Computer Science and Engineering"
    assert edges[("career:cse", "fits_trait", "trait:investigative")].weight == pytest.approx(0.667, abs=1e-3)
    assert edges[("career:cse", "related_subject", "subject:mathematics")].source["ref"] == "careers.json"
    assert edges[("career:cse", "requires_skill", "skill:python")].attrs == {"level": "intermediate", "importance": 0.9}
    assert keys["exam:JEE_MAIN"].source["url"] == "https://jeemain.nta.nic.in"
    assert version.unmatched["names"] == [{"name": "B.Tech | Mining Engineering", "count": 1}], "reported, not guessed"
    assert version.counts["nodes"]["career"] == 1


def test_loading_again_with_nothing_changed_does_nothing(db_session, graph_dir, official):
    first = ensure_graph(db_session, graph_dir)
    assert ensure_graph(db_session, graph_dir).id == first.id
    assert db_session.query(KgVersion).count() == 1


def test_a_change_to_the_knowledge_or_the_official_data_reloads(db_session, graph_dir, official):
    first = ensure_graph(db_session, graph_dir)
    (graph_dir / "graph.yaml").write_text(GRAPH.replace("Technology, hi: टेक्नोलॉजी", "Tech, hi: टेक"))
    second = ensure_graph(db_session, graph_dir)
    assert second.id != first.id and db_session.get(KgNode, db_session.query(KgNode.id).filter_by(
        key="domain:technology").scalar()).name["en"] == "Tech"
    other = College(canonical_name="IIIT Example", college_type="IIIT", ownership="government", state="Kerala",
                    city="Kottayam", is_demo_data=False)
    db_session.add(other)
    db_session.commit()
    assert ensure_graph(db_session, graph_dir).id != second.id
    assert db_session.query(KgNode).filter_by(key=f"college:{other.id}").count() == 1


def test_a_broken_graph_is_refused_and_the_old_one_stays(db_session, graph_dir, official):
    ensure_graph(db_session, graph_dir)
    nodes = db_session.query(KgNode).count()
    (graph_dir / "graph.yaml").write_text(GRAPH.replace("requires_exam: [exam:JEE_MAIN]", "requires_exam: [exam:NOPE]"))
    with pytest.raises(GraphInvalid, match="'exam:NOPE' doesn't exist"):
        ensure_graph(db_session, graph_dir)
    db_session.rollback()
    assert db_session.query(KgNode).count() == nodes


def snapshot(**extra_edges):
    curated = Source(kind="curated", ref="t")
    snap = Snapshot()
    for key in ("career:a", "degree:d", "subject:s", "skill:x", "skill:y", "skill:z", "domain:t"):
        snap.node(key, {"en": key, "hi": key}, curated)
    snap.edge("career:a", "entered_through", "degree:d", curated)
    snap.edge("career:a", "part_of", "domain:t", curated)
    snap.edge("career:a", "requires_skill", "skill:x", curated)
    snap.edge("degree:d", "requires_subject", "subject:s", curated)
    for (src, edge_type, dst) in extra_edges.get("edges", []):
        snap.edge(src, edge_type, dst, curated)
    return snap


@pytest.mark.parametrize("edges, message", [
    ([("skill:x", "skill_prerequisite", "skill:y"), ("skill:y", "skill_prerequisite", "skill:z"),
      ("skill:z", "skill_prerequisite", "skill:x")], "prerequisite cycle"),
    ([("career:a", "requires_skill", "degree:d")], "can't be on that end of requires_skill"),
    ([("career:a", "teleports_to", "skill:x")], "unknown edge type"),
])
def test_the_validator_names_each_problem(edges, message):
    with pytest.raises(GraphInvalid, match=message):
        validate(snapshot(edges=edges))


def test_every_career_needs_a_route_and_every_degree_its_subjects():
    snap = snapshot()
    del snap.edges[("career:a", "entered_through", "degree:d")]
    del snap.edges[("degree:d", "requires_subject", "subject:s")]
    with pytest.raises(GraphInvalid) as e:
        validate(snap)
    assert "career:a: no entered_through edge" in e.value.problems
    assert "degree:d: no requires_subject edge" in e.value.problems


def test_the_library_and_the_graph_must_agree():
    with pytest.raises(GraphInvalid) as e:
        validate(snapshot(), library=[{"key": "b"}])
    assert e.value.problems == ["career:b: in careers.json but not in the graph", "career:a: in the graph but not in careers.json"]


def test_measured_by_must_name_a_real_assessment_dimension():
    snap = snapshot()
    snap.nodes["skill:x"]["attrs"]["measured_by"] = ["skill:telepathy"]
    with pytest.raises(GraphInvalid, match="measured_by 'skill:telepathy'"):
        validate(snap, measures={"skill:programming"})


def test_build_works_without_any_official_data(db_session, graph_dir):
    snap = build(db_session, graph_dir)
    assert "career:cse" in snap.nodes and not any(t == "offered_at" for (_s, t, _d) in snap.edges)
