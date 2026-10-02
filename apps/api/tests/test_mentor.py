"""The continuous mentor's brief and agenda: every module contributes what's worth raising, ranked
without a model; nothing is raised twice in a session; 'not now' means two weeks; memory-based
items need the memory permission."""

from datetime import datetime, timedelta, timezone

from app.facts import store
from app.memory import consent
from app.mentor import agenda, brief
from app.models.chat import Conversation
from app.models.college import College
from app.models.exam import Exam
from app.models.memory import CounsellingThread, StudentGoal
from app.models.saved_item import SavedItem
from app.seed.careers import seed_careers
from tests.test_assessment_service import GUARDIAN, right, student, take

NOW = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)


def thread(db, profile, title, decision="undecided", question=None, position=""):
    th = CounsellingThread(student_profile_id=profile.id, topic_key="stream_choice", title=title, status="open",
                           decision_status=decision, current_position=position,
                           open_questions=[question] if question else [], actions_agreed=[], last_touched_at=NOW - timedelta(days=10))
    db.add(th)
    db.flush()
    return th


def test_an_undecided_topic_needs_the_memory_permission(db_session):
    asha = student(db_session)
    thread(db_session, asha, "PCM vs PCB", question="Will my parents accept PCM?")
    assert agenda.topics(db_session, asha, NOW) == [], "threads are memory"
    consent.decide(db_session, asha, consent.LONG_TERM_MEMORY, True, GUARDIAN)
    [item] = agenda.topics(db_session, asha, NOW)
    assert item.title["en"] == "PCM vs PCB" and item.priority == 65
    assert "still open: Will my parents accept PCM?" in item.why["en"]


def test_a_reassessment_is_due_after_six_months_or_a_new_class(db_session):
    from app.roadmap import service

    asha = student(db_session, class_level=10)
    seed_careers(db_session)
    service.current(db_session, asha)  # roadmap v1 remembers class 10
    take(db_session, asha, "aptitude", choose=right)
    assert agenda.reassessments(db_session, asha, datetime.now(timezone.utc)) == []
    asha.class_level = 11
    db_session.commit()
    [moved] = agenda.reassessments(db_session, asha, datetime.now(timezone.utc))
    assert moved.key == "reassess:aptitude" and moved.priority == 55 and "class 10" in moved.why["en"]
    asha.class_level = 10
    db_session.commit()
    [aged] = agenda.reassessments(db_session, asha, datetime.now(timezone.utc) + timedelta(days=200))
    assert aged.priority == 50 and "6 months" in aged.why["en"]


def test_dates_for_their_exam(db_session):
    asha = student(db_session)
    asha.target_exam_code = "JEE_MAIN"
    exam = Exam(code="JEE_MAIN", name="JEE Main", category="engineering")
    db_session.add(exam)
    db_session.flush()
    src = store.source(db_session, "nta", "NTA", 3)
    doc = store.document(db_session, src, "https://nta.ac.in/bulletin.pdf", "JEE Main 2027 bulletin", NOW, sha256="a" * 64)
    store.record(db_session, "exam", exam.id, "admission.application_window.session_1",
                 {"from": "2026-10-31", "to": "2026-11-27", "label": "Applications, session 1"}, document=doc,
                 academic_year="2027-28", quote="…", now=NOW)
    items = {i.key: i for i in agenda.dates(db_session, asha, NOW)}
    window = items["dates:JEE_MAIN:admission.application_window.session_1:2026-10-31"]
    assert window.priority == 75 and window.why["en"] == "In 29 days"
    assert items["dates:JEE_MAIN:announced:2027-28"].priority == 70
    assert agenda.dates(db_session, asha, NOW + timedelta(days=26))[0].priority == 90, "within a week"


def test_a_shortlisted_colleges_news(db_session):
    asha = student(db_session)
    manit = College(canonical_name="MANIT Bhopal", college_type="NIT", ownership="government", state="MP", city="Bhopal",
                    is_demo_data=False)
    db_session.add(manit)
    db_session.flush()
    db_session.add(SavedItem(student_profile_id=asha.id, item_type="college", item_id=manit.id))
    db_session.add(Conversation(student_profile_id=asha.id, ended_at=datetime.now(timezone.utc) - timedelta(days=3)))
    db_session.flush()
    src = store.source(db_session, "site-manit", "MANIT (official website)", 2)
    doc = store.document(db_session, src, "https://manit.ac.in/fees.pdf", "Fees 2026-27", NOW, sha256="b" * 64)
    store.record(db_session, "college", manit.id, "fee.tuition.annual", {"amount": 62500, "per": "semester"},
                 document=doc, academic_year="2026-27", quote="…", now=NOW)
    db_session.commit()
    [item] = agenda.colleges(db_session, asha, datetime.now(timezone.utc))
    assert item.title["en"] == "MANIT Bhopal" and "Tuition fee" in item.why["en"] and item.screen["page"] == "college_detail"


def test_decisions_become_proposals(db_session):
    asha = student(db_session, memory=True)
    seed_careers(db_session)
    thread(db_session, asha, "PCM vs PCB", decision="decided", position="Going with PCB, to become a doctor")
    keys = {i.key for i in agenda.decisions(db_session, asha, NOW)}
    assert "decision:stream:PCB" in keys
    assert "decision:stream:PCM" not in keys, "the topic's title names both; the decision says PCB"
    assert "decision:focus:career:mbbs" in keys, "a career named in a decision is proposed as the focus"
    thread(db_session, asha, "Career", decision="decided", position="Doctor rather than engineer, and PCM or PCB later")
    assert {i.key for i in agenda.decisions(db_session, asha, NOW)} == keys, "two careers or two streams named: no guess"


def test_never_nag(db_session):
    asha = student(db_session, memory=True)
    thread(db_session, asha, "PCM vs PCB")
    db_session.add(StudentGoal(student_profile_id=asha.id, title="Learn Python", kind="skill", status="active"))
    db_session.flush()
    session_start = datetime.now(timezone.utc)
    later = session_start + timedelta(days=50)
    first = agenda.to_raise(db_session, asha, later, session_start)
    assert [i.kind for i in first] == ["topic", "goal"], "at most two, best first"
    agenda.mark(db_session, asha, first[0].key, "raised", now=later)
    assert [i.kind for i in agenda.to_raise(db_session, asha, later, session_start)] == ["goal"], "not twice a session"
    agenda.mark(db_session, asha, "thread:%s" % first[0].key.split(":")[1], "not_now", now=later)
    assert all(i.kind != "topic" for i in agenda.agenda(db_session, asha, later + timedelta(days=13)))
    assert any(i.kind == "topic" for i in agenda.agenda(db_session, asha, later + timedelta(days=15))), "back after two weeks"
    agenda.mark(db_session, asha, first[1].key, "done", now=later)
    assert all(i.kind != "goal" for i in agenda.agenda(db_session, asha, later + timedelta(days=100)))


def test_the_brief_answers_the_eight_questions(db_session):
    asha = student(db_session)
    thread(db_session, asha, "PCM vs PCB", question="Will my parents accept PCM?")
    without = brief.brief(db_session, asha, NOW)
    assert without["memory"] is False and without["discussed"] == [] and "permission is off" in without["note"]
    consent.decide(db_session, asha, consent.LONG_TERM_MEMORY, True, GUARDIAN)
    full = brief.brief(db_session, asha, NOW)
    assert set(full) >= {"who", "discussed", "confused", "decided", "working_toward", "progress", "last_stopped", "next"}
    assert full["confused"][0]["question"] == "Will my parents accept PCM?"
    assert full["last_stopped"]["current_counselling_topic"] == "PCM vs PCB"
    assert full["next"][0]["kind"] == "topic" and full["who"]["class_level"] == 10


def test_the_mentor_api(client):
    from tests.test_assessment_api import auth
    from tests.test_conversation_ws import register

    token = register(client)
    assert client.get("/api/mentor/brief", headers=auth(token)).json()["who"]["class_level"] == 10
    [step] = client.get("/api/mentor/agenda", headers=auth(token)).json()
    assert step["key"] == "roadmap:next:task:assessment:interests" and step["screen"]["page"] == "roadmap_node", \
        "a new student's first roadmap step"
    marked = client.post("/api/mentor/agenda/mark", json={"key": "thread:1", "what": "not_now"}, headers=auth(token)).json()
    assert marked["status"] == "dismissed" and marked["snoozed_until"]
    assert client.post("/api/mentor/agenda/mark", json={"key": "x", "what": "forget"}, headers=auth(token)).status_code == 400
    assert client.get("/api/mentor/brief").status_code == 401
