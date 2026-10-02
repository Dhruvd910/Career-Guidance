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
    assert moved.key.startswith("reassess:aptitude:") and moved.priority == 55 and "class 10" in moved.why["en"]
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



def test_a_stream_changes_only_when_the_student_asks(db_session):
    from app.ai.tools import execute_tool
    from app.models.memory import StudentEvent
    from app.roadmap import service

    asha = student(db_session, memory=True)
    seed_careers(db_session)
    thread(db_session, asha, "Stream", decision="decided", position="PCM final; computer science is the goal")
    keys = {i.key for i in agenda.decisions(db_session, asha, NOW)}
    assert {"decision:stream:PCM", "decision:focus:career:cse"} <= keys, "'computer science' is the CSE career"
    assert asha.stream != "PCM", "proposed, not applied"

    service.current(db_session, asha)
    done = execute_tool(db_session, asha, "set_my_stream", {"stream": "pcm"})
    assert done["changed"] and asha.stream == "PCM" and "Saved" in done["note"]
    assert "decision:stream:PCM" not in {i.key for i in agenda.decisions(db_session, asha, NOW)}
    assert db_session.query(StudentEvent).filter_by(student_profile_id=asha.id, event_type="PROFILE_UPDATED").count() == 1
    assert execute_tool(db_session, asha, "set_my_stream", {"stream": "PCM"})["changed"] is False
    assert "error" in execute_tool(db_session, asha, "set_my_stream", {"stream": "science"})


def test_one_quiet_goal_at_a_time(db_session):
    asha = student(db_session, memory=True)
    for title, days in (("Learn Python", 60), ("Decide a stream", 90), ("Build a project", 50)):
        db_session.add(StudentGoal(student_profile_id=asha.id, title=title, kind="skill", status="active",
                                   created_at=NOW - timedelta(days=days), updated_at=NOW - timedelta(days=days)))
    db_session.flush()
    quiet = agenda.goals(db_session, asha, NOW)
    assert [i.title["en"] for i in quiet] == ["Decide a stream"], "the quietest, not a list"
    agenda.mark(db_session, asha, quiet[0].key, "done", now=NOW)
    assert [i.title["en"] for i in agenda.goals(db_session, asha, NOW)] == ["Learn Python"], "the next makes way"


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


def test_the_shortlist(client, db_session):
    from app.ai.tools import execute_tool
    from app.mentor import shortlist
    from app.models.memory import StudentEvent
    from app.roadmap import service

    seed_careers(db_session)
    asha = student(db_session, class_level=12, memory=True)
    asha.state = "Madhya Pradesh"
    manit = College(canonical_name="Maulana Azad National Institute of Technology Bhopal", college_type="NIT",
                    ownership="government", state="Madhya Pradesh", city="Bhopal", is_demo_data=False,
                    aliases=["MANIT", "NIT Bhopal"])
    other = College(canonical_name="National Institute of Technology Raipur", college_type="NIT", ownership="government",
                    state="Chhattisgarh", city="Raipur", is_demo_data=False, aliases=["NIT Raipur"])
    db_session.add_all([manit, other])
    db_session.commit()
    service.adapt(db_session, asha, "focus", career="cse")
    added = execute_tool(db_session, asha, "shortlist_college", {"college": "MANIT"})
    assert added == {"added": manit.canonical_name, "shortlist": 1}
    step = next(n for n in _walk(service.view(db_session, asha)["stages"]) if n["node_key"] == "module:colleges")
    assert step["status"] == "in_progress" and step["evidence"][-1]["note"] == "1 colleges shortlisted"
    assert db_session.query(StudentEvent).filter_by(event_type="COLLEGE_SHORTLISTED").count() == 1
    assert "Which one?" in execute_tool(db_session, asha, "shortlist_college", {"college": "National Institute"})["error"]
    assert execute_tool(db_session, asha, "my_shortlist", {})["colleges"][0]["name"] == manit.canonical_name
    assert shortlist.remove(db_session, asha, manit.id)["shortlist"] == 0
    assert execute_tool(db_session, asha, "my_shortlist", {})["colleges"] == []


def _walk(nodes):
    for n in nodes:
        yield n
        yield from _walk(n["children"])


def test_a_session_summary_records_what_happened(db_session):
    from app.mentor import shortlist
    from app.roadmap import service
    from tests.fakes import FakeLLM
    from tests.test_memory_writer import TRANSCRIPT, notes, session, write
    from tests.test_memory_writer import student as memory_student

    seed_careers(db_session)
    asha = memory_student(db_session)
    conversation, ids = session(db_session, asha, *TRANSCRIPT)
    service.adapt(db_session, asha, "focus", career="cse")
    take(db_session, asha, "aptitude", choose=right)
    manit = College(canonical_name="MANIT Bhopal", college_type="NIT", ownership="government", state="MP", city="Bhopal",
                    is_demo_data=False)
    db_session.add(manit)
    db_session.commit()
    shortlist.add(db_session, asha, manit.id)
    summary = write(db_session, conversation, FakeLLM(notes(ids)))
    kinds = {h["kind"] for h in summary.happened}
    assert {"roadmap", "assessment", "shortlist"} <= kinds
    [took] = [h["what"] for h in summary.happened if h["kind"] == "assessment"]
    assert took.startswith("Took “") and took.endswith("”")
    assert "Shortlisted MANIT Bhopal" in [h["what"] for h in summary.happened]
    assert summary.roadmap_changes and summary.roadmap_changes[0]["trigger"] in ("initial", "focus"), \
        "roadmap changes come from the roadmap, not the model"
    assert summary.schema_version == 2


def test_maya_raises_things_once_and_honours_not_now(db_session):
    import asyncio

    from app.ai.tools import execute_tool
    from app.memory.opening import opening_line
    from app.mentor.context import mentor_context
    from tests.fakes import FakeLLM

    asha = student(db_session)  # no memory permission: only account data is raised
    asha.target_exam_code = "JEE_MAIN"
    exam = Exam(code="JEE_MAIN", name="JEE Main", category="engineering")
    db_session.add(exam)
    db_session.add(Conversation(student_profile_id=asha.id, ended_at=NOW - timedelta(days=5)))
    db_session.flush()
    src = store.source(db_session, "nta", "NTA", 3)
    doc = store.document(db_session, src, "https://nta.ac.in/b.pdf", "JEE Main 2027 bulletin", NOW, sha256="c" * 64)
    store.record(db_session, "exam", exam.id, "admission.application_window.session_1",
                 {"from": "2026-10-31", "to": "2026-11-27", "label": "Applications, session 1"}, document=doc,
                 academic_year="2027-28", quote="…", now=NOW)
    db_session.commit()

    llm = FakeLLM("Welcome back, Asha — JEE Main 2027 applications open on 31 October. Where shall we start?")
    text, _ = asyncio.run(opening_line(db_session, asha, llm, now=NOW))
    assert "31 October" in text and "worth_raising" in llm.seen[0][1]["content"], "a return without an open topic still opens"
    later = mentor_context(db_session, asha, session_started=NOW, now=NOW + timedelta(minutes=1))
    assert "Worth raising" not in later and "what_next" in later, "already raised in the opening: not again this session"

    nxt = execute_tool(db_session, asha, "what_next", {})
    keys = [i["key"] for i in nxt["items"]]
    assert "dates:JEE_MAIN:announced:2027-28" in keys
    assert execute_tool(db_session, asha, "update_agenda", {"key": keys[0], "what": "not_now"})["status"] == "dismissed"
    assert keys[0] not in [i["key"] for i in execute_tool(db_session, asha, "what_next", {})["items"]]


def test_every_reply_carries_the_mentor(client, monkeypatch):
    from app.ai import orchestrator
    from tests.fakes import FakeLLM
    from tests.test_assessment_api import auth
    from tests.test_conversation_ws import register

    token = register(client)
    client.get("/api/roadmap", headers=auth(token))  # their first roadmap
    llm = FakeLLM("Okay.", "Okay.")
    monkeypatch.setattr(orchestrator, "get_llm_provider", lambda: llm)
    first = client.post("/api/ai/chat", json={"message": "Aaj kya baat karein?"}, headers=auth(token)).json()
    client.post("/api/ai/chat", json={"message": "Aur?", "conversation_id": first["conversation_id"]}, headers=auth(token))
    later = "\n".join(m["content"] for m in llm.seen[1] if m["role"] == "system")
    assert "Worth raising" not in later, "raised once a session"
    system = "\n".join(m["content"] for m in llm.seen[0] if m["role"] == "system")
    assert "never start them from zero" in system and "call what_next" in system
    assert "Worth raising if it fits" in system and "roadmap:next:" in system, "their first roadmap step"
