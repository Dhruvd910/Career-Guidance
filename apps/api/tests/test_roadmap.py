"""Roadmaps: class-aware spines, built from the career graph, versioned, adapting to spec §19's
sentences without losing history or progress, and skill progress from measurements only."""

from datetime import date

import pytest

from app.knowledge.graph_store import graph
from app.memory import consent
from app.models.memory import StudentEvent
from app.models.roadmap import RoadmapNode, RoadmapVersion, SkillMeasurement
from app.roadmap import progress, service
from app.roadmap.generator import Inputs, build
from app.roadmap.templates import templates
from app.seed.careers import seed_careers
from tests.test_assessment_service import right, student, take

TODAY = date(2026, 10, 1)
GUARDIAN = {"name": "Sunita", "relationship": "mother", "contact": "x"}


@pytest.fixture()
def store(db_session):
    seed_careers(db_session)
    return graph(db_session)


def tree(nodes):
    return {n["node_key"]: n for n in nodes}


def milestones(nodes, stage):
    return [n["node_key"].split(":")[-1] for n in nodes if n["kind"] == "milestone" and n["stage"] == stage
            and n["parent_key"] == f"stage:{stage}" and not n["node_key"].endswith("strengthen")]


@pytest.mark.parametrize("inputs, band, stage", [
    (Inputs(class_level=8), "class_6_8", "class_8"),
    (Inputs(class_level=10), "class_9_10", "class_10"),
    (Inputs(class_level=12), "class_11_12", "class_12"),
    (Inputs(class_level=12, education_stage="dropper"), "dropper", "dropper"),
    (Inputs(class_level=12, education_stage="ug_y2"), "college", "degree"),
])
def test_each_stage_gets_its_own_spine(store, inputs, band, stage):
    nodes = build(store, inputs, TODAY)
    assert nodes[0]["node_key"] == f"stage:{stage}" and nodes[0]["attrs"]["current"]
    assert milestones(nodes, stage) == [m.key for m in templates().bands[band].spine]


def test_later_stages_follow_the_school_calendar(store):
    nodes = tree(build(store, Inputs(class_level=10), TODAY))
    stages = [k for k, n in nodes.items() if n["kind"] == "stage"]
    assert stages == ["stage:class_10", "stage:class_11", "stage:class_12", "stage:degree", "stage:specialisation",
                      "stage:internship", "stage:career"]
    assert nodes["stage:class_11"]["window"] == {"from": "2027-04", "to": "2028-03"}


def test_the_same_inputs_give_the_same_roadmap(store):
    inputs = Inputs(class_level=10, focus="ai_data", state="Madhya Pradesh")
    assert build(store, inputs, TODAY) == build(store, inputs, TODAY)


def test_a_focus_brings_its_skills_in_prerequisite_order_and_at_the_right_age(store):
    nodes = tree(build(store, Inputs(class_level=10, focus="ai_data", hours_per_week=10), TODAY))
    keys = list(nodes)
    assert nodes["module:skill:probability_statistics"]["stage"] == "class_10"
    assert nodes["module:skill:calculus"]["stage"] == "class_11", "calculus isn't class 10 work"
    assert nodes["module:skill:machine_learning"]["stage"] == "degree"
    assert keys.index("module:skill:python") < keys.index("module:skill:data_analysis") < keys.index("module:skill:machine_learning")
    assert "module:skill:data_analysis" in nodes["module:skill:machine_learning"]["prerequisites"]
    assert nodes["module:skill:python"]["detail"]["how"], "with things to try"
    assert any(k.startswith("task:project:") for k in keys)
    assert nodes["module:exam:JEE_MAIN"]["attrs"]["exam_critical"] and nodes["module:exam:JEE_MAIN"]["stage"] == "class_12"


def test_not_enough_time_defers_optional_work_but_never_exams(store):
    nodes = tree(build(store, Inputs(class_level=12, focus="ai_data", hours_per_week=1), TODAY))
    deferred = [k for k, n in nodes.items() if n["state"] == "deferred"]
    assert deferred and all(nodes[k]["attrs"].get("optional") for k in deferred)
    assert all(n["state"] == "active" for n in nodes.values() if n["attrs"].get("exam_critical"))
    assert "1 hour a week" in nodes[deferred[0]]["attrs"]["reason"]["en"]


def test_a_hard_subject_gets_a_foundation_before_everything_built_on_it(store):
    nodes = tree(build(store, Inputs(class_level=10, focus="ai_data", difficulties=["mathematics"]), TODAY))
    foundation = nodes["module:foundation:mathematics"]
    assert foundation["attrs"]["reason"]["en"] == "Added because you said maths feels hard."
    assert "module:skill:school_mathematics" not in nodes, "the foundation module stands in for it"
    assert "module:foundation:mathematics" in nodes["module:skill:probability_statistics"]["prerequisites"]
    assert "module:foundation:mathematics" in nodes["module:exam:JEE_MAIN"]["prerequisites"]


# ---------------- versions and adaptation ----------------

def _ready(db, memory=True):
    asha = student(db, class_level=10, memory=memory)
    asha.state = "Madhya Pradesh"
    db.commit()
    service.adapt(db, asha, "focus", career="AI")
    return asha


def test_the_first_roadmap_and_the_three_sentences_of_spec_19(db_session, store):
    asha = _ready(db_session)
    v = service.view(db_session, asha)
    assert v["version"] == 2 and v["focus"]["key"] == "ai_data", "v1 when first asked for, v2 with the focus"
    v1_nodes = {n.node_key: (n.state, n.stage) for n in db_session.query(RoadmapNode).join(RoadmapVersion)
                .filter(RoadmapVersion.version_no == 1)}
    service.update_progress(db_session, asha, "module:skill:logical_reasoning", "done", note="did olympiad sets")

    # "I only have two hours a day" — from plenty of time to 1 hour a week for the roadmap.
    service.adapt(db_session, asha, "time_budget", hours_per_week=12)
    time = service.adapt(db_session, asha, "time_budget", detail="only 2 hours a day", hours_per_week=1)
    assert time["changed"] and any(c["op"] == "defer" for c in time["changes"])
    assert any(c["op"] == "modify" for c in time["changes"]), "and the rest moves to later months"
    assert service.view(db_session, asha)["time"]["hours_available"] < service.view(db_session, asha)["time"]["hours_needed"]

    # "Maths is difficult for me."
    maths = service.adapt(db_session, asha, "difficulty", subject="maths")
    added = next(c for c in maths["changes"] if c["node_key"] == "module:foundation:mathematics")
    assert added["op"] == "add" and "you said maths feels hard" in added["reason"]["en"]

    # "I no longer want AI. I'm interested in cybersecurity."
    swap = service.adapt(db_session, asha, "interest_change", career="cybersecurity", dropping="AI")
    v = service.view(db_session, asha)
    assert v["focus"]["key"] == "cybersecurity" and v["dropped"][0]["key"] == "ai_data"
    parked = [c for c in swap["changes"] if c["op"] in ("park", "add") and c["node_key"].startswith("module:skill:")]
    states = {n["node_key"]: n["state"] for n in _flat(v["stages"])}
    assert states.get("module:skill:machine_learning") == "parked", "AI-only work is parked, not deleted"
    assert states.get("module:skill:computer_networks") == "active"
    assert parked

    # History is intact and progress carried over.
    assert [x["version"] for x in service.versions(db_session, asha)] == [1, 2, 3, 4, 5, 6]
    assert {n.node_key: (n.state, n.stage) for n in db_session.query(RoadmapNode).join(RoadmapVersion)
            .filter(RoadmapVersion.version_no == 1)} == v1_nodes, "version 1 never changes"
    logic = next(n for n in _flat(v["stages"]) if n["node_key"] == "module:skill:logical_reasoning")
    assert logic["status"] == "done" and logic["evidence"][0]["note"] == "did olympiad sets"
    old = service.view(db_session, asha, version_no=2)
    assert old["version"] == 2 and "module:skill:machine_learning" in {n["node_key"] for n in _flat(old["stages"])}
    assert next(n for n in _flat(old["stages"]) if n["node_key"] == "module:skill:machine_learning")["state"] == "active"


def _flat(nodes):
    for n in nodes:
        yield n
        yield from _flat(n["children"])


def test_exploring_a_second_career_adds_a_branch(db_session, store):
    asha = _ready(db_session)
    service.adapt(db_session, asha, "interest_change", career="robotics")
    v = service.view(db_session, asha)
    assert v["focus"]["key"] == "ai_data" and [b["key"] for b in v["branches"]] == ["robotics"]
    branch = next(n for n in _flat(v["stages"]) if n["node_key"] == "branch:robotics")
    assert branch["kind"] == "branch" and branch["children"]


def test_nothing_new_when_only_the_month_moved_on(db_session, store):
    asha = _ready(db_session)
    count = db_session.query(RoadmapVersion).count()
    assert service.rebuild(db_session, asha, {"kind": "manual"}, today=date(2026, 11, 1)) is None
    assert db_session.query(RoadmapVersion).count() == count


def test_a_measured_strength_completes_its_module_with_the_evidence(db_session, store):
    asha = _ready(db_session)
    take(db_session, asha, "aptitude", choose=right)  # the reassessment hook rebuilds
    v = service.view(db_session, asha)
    logic = next(n for n in _flat(v["stages"]) if n["node_key"] == "module:skill:logical_reasoning")
    assert logic["status"] == "done" and logic["evidence"][0]["kind"] == "assessment"
    assert logic["evidence"][0]["says"]["en"] == "5 of 5 right"
    assessment = next(n for n in _flat(v["stages"]) if n["node_key"] == "task:assessment:aptitude")
    assert assessment["status"] == "done"


def test_the_next_step_waits_for_what_it_builds_on(db_session, store):
    asha = _ready(db_session)
    first = service.next_step(db_session, asha)
    assert first["node_key"] == "task:assessment:interests"
    for key in ("task:assessment:interests", "task:assessment:aptitude", "task:assessment:skills", "task:assessment:academic"):
        service.update_progress(db_session, asha, key, "done")
    later = service.next_step(db_session, asha)
    v = {n["node_key"]: n for n in _flat(service.view(db_session, asha)["stages"])}
    assert all(v[p]["status"] == "done" or v[p]["state"] != "active" for p in v[later["node_key"]]["prerequisites"])


def test_progress_only_on_real_steps(db_session, store):
    asha = _ready(db_session)
    with pytest.raises(service.RoadmapError) as e:
        service.update_progress(db_session, asha, "module:skill:telepathy", "done")
    assert e.value.not_found
    with pytest.raises(service.RoadmapError):
        service.update_progress(db_session, asha, "task:assessment:interests", "finished")


def test_the_timeline_only_with_the_memory_permission(db_session, store):
    _ready(db_session, memory=False)
    assert db_session.query(StudentEvent).count() == 0
    ravi = student(db_session, "ravi", class_level=10)
    consent.decide(db_session, ravi, consent.LONG_TERM_MEMORY, True, GUARDIAN)
    service.adapt(db_session, ravi, "focus", career="law")
    types = [e.event_type for e in db_session.query(StudentEvent).filter_by(student_profile_id=ravi.id)]
    assert types == ["ROADMAP_CREATED", "FOCUS_CHOSEN", "ROADMAP_UPDATED"]


# ---------------- skill progress ----------------

def test_skill_progress_from_measurements_only(db_session, store):
    asha = _ready(db_session)
    take(db_session, asha, "aptitude", choose=lambda i: right(i, wrong={"a_log_1", "a_log_2", "a_log_3"}))
    take(db_session, asha, "aptitude", choose=right)
    service.update_progress(db_session, asha, "module:skill:probability_statistics", "done")
    series = {s["skill"]: s for s in progress.skill_series(db_session, asha)}
    logic = series["skill:logical_reasoning"]
    assert (logic["initial"], logic["current"], logic["change"]) == (0.4, 1.0, 1)
    assert logic["points"][0]["says"]["en"] == "2 of 5 right" and logic["points"][0]["source"] == "assessment"
    assert "skill:probability_statistics" not in series, "ticking a module done isn't a measurement"
    assert db_session.query(SkillMeasurement).filter_by(skill_key="skill:problem_solving").count() == 2


def test_practice_papers_count_too(db_session, store):
    from app.models.exam import Exam
    from app.models.practice import TestAttempt

    asha = _ready(db_session)
    exam = Exam(code="JEE_MAIN", name="JEE Main", category="engineering")
    db_session.add(exam)
    db_session.flush()
    paper = TestAttempt(student_profile_id=asha.id, exam_id=exam.id, mode="full", duration_seconds=3600,
                        total_questions=10, submitted_at=TODAY,
                        subject_scores={"Physics": {"correct": 3, "wrong": 1, "unanswered": 1}})
    db_session.add(paper)
    db_session.commit()
    progress.record_practice(db_session, paper)
    db_session.commit()
    physics = next(s for s in progress.skill_series(db_session, asha) if s["skill"] == "skill:physics_fundamentals")
    assert physics["current"] == 0.6 and physics["points"][0]["says"]["en"] == "3 of 5 right in a practice paper"
