"""MAYA and the roadmap: what she knows in every reply, and her tools."""

from app.ai import orchestrator
from app.ai.tools import TOOL_SPECS, execute_tool
from app.roadmap.context import NONE_YET, roadmap_context
from app.seed.careers import seed_careers
from tests.fakes import FakeLLM
from tests.test_assessment_service import right, scripted, student, take
from tests.test_conversation_ws import register


def ready(db):
    seed_careers(db)
    asha = student(db, class_level=10)
    asha.state = "Madhya Pradesh"
    db.commit()
    return asha


def test_the_tools_replace_the_old_template():
    names = {t["function"]["name"] for t in TOOL_SPECS}
    assert "generate_roadmap" not in names
    assert {"get_my_roadmap", "roadmap_next_step", "adjust_roadmap", "set_roadmap_focus", "update_roadmap_progress",
            "my_progress", "exam_study_plan"} <= names


def test_context_before_and_after_a_roadmap(db_session):
    asha = ready(db_session)
    assert roadmap_context(db_session, asha) == NONE_YET, "talking to MAYA doesn't make a roadmap"
    execute_tool(db_session, asha, "set_roadmap_focus", {"career": "AI"})
    execute_tool(db_session, asha, "adjust_roadmap", {"save": True, "kind": "difficulty", "subject": "maths"})
    text = roadmap_context(db_session, asha)
    assert "focus Data Science & Artificial Intelligence" in text and "Now: Class 10" in text
    assert "Next step: Maths foundation — why: Added because you said maths feels hard." in text, \
        "the foundation comes first once maths is hard, with its reason"
    assert "Last change: " in text and "add Maths foundation — Added because you said maths feels hard" in text


def test_next_step_and_progress(db_session):
    asha = ready(db_session)
    execute_tool(db_session, asha, "set_roadmap_focus", {"career": "cse"})
    step = execute_tool(db_session, asha, "roadmap_next_step", {})
    assert step["next_step"] == "What you enjoy" and step["done_when"] == "You've taken it once."
    done = execute_tool(db_session, asha, "update_roadmap_progress", {"step": "logical reasoning", "status": "done"})
    assert done["updated"] == "Logical reasoning" and "not a measured skill level" in done["note"]
    vague = execute_tool(db_session, asha, "update_roadmap_progress", {"step": "I finished the course"})
    assert vague["error"].startswith("Which step?")
    stray = execute_tool(db_session, asha, "update_roadmap_progress", {"step": "foundation skills and logic"})
    assert stray["error"].startswith("Which step?"), "one stray word never ticks a step"
    said = execute_tool(db_session, asha, "update_roadmap_progress", {"step": "problem solving wala step", "status": "in_progress"})
    assert said["updated"] == "Problem solving"
    course = execute_tool(db_session, asha, "update_roadmap_progress", {"step": "logical reasoning course"})
    assert course["updated"] == "Logical reasoning", "mostly the same words"
    roadmap = execute_tool(db_session, asha, "get_my_roadmap", {})
    now = roadmap["stages"][0]
    assert now["now"] and any(s["step"] == "Logical reasoning" and s["status"] == "done" for s in now["steps"])
    assert roadmap["focus"] == "Computer Science & Software Engineering"


def test_the_three_sentences_through_the_tools(db_session):
    asha = ready(db_session)
    execute_tool(db_session, asha, "set_roadmap_focus", {"career": "AI"})
    time = execute_tool(db_session, asha, "adjust_roadmap", {"save": True, "kind": "time_budget", "hours_a_day": 2,
                                                             "detail": "only two hours a day"})
    assert time["new_version"] == 3 and "finished still counts" in time["note"]
    assert time["hours_per_week"] == 2, "two hours a day of study in all is less roadmap time, never more"
    assert time["hours"].startswith("2 hours a day of study in all leaves about 2 hours a week")
    maths = execute_tool(db_session, asha, "adjust_roadmap", {"save": True, "kind": "difficulty", "subject": "Maths"})
    assert {"change": "add", "step": "Maths foundation", "reason": "Added because you said maths feels hard."} in maths["changes"]
    swap = execute_tool(db_session, asha, "adjust_roadmap", {"save": True, "kind": "interest_change", "career": "cybersecurity",
                                                             "dropping": "AI"})
    assert any(c["change"] == "park" for c in swap["changes"])
    assert swap["focus"] == "Cybersecurity" and swap["moved_away_from"] == ["Data Science & Artificial Intelligence"]
    assert execute_tool(db_session, asha, "get_my_roadmap", {})["moved_away_from"] == ["Data Science & Artificial Intelligence"]
    assert "error" in execute_tool(db_session, asha, "adjust_roadmap", {"save": True, "kind": "difficulty", "subject": "dance"})
    assert "hours_a_day" in execute_tool(db_session, asha, "adjust_roadmap", {"save": True, "kind": "time_budget"})["error"]
    more = execute_tool(db_session, asha, "adjust_roadmap", {"save": True, "kind": "interest_change", "career": "robotics"})
    assert more["focus"] == "Cybersecurity" and more["exploring"] == ["Robotics & Automation"], "without dropping, it's a branch"


def test_how_much_have_i_improved(db_session):
    asha = ready(db_session)
    take(db_session, asha, "aptitude", choose=scripted({"aptitude:logical": [False, False, False, True, True]}))
    take(db_session, asha, "aptitude", choose=right)
    out = execute_tool(db_session, asha, "my_progress", {})
    logic = next(s for s in out["skills"] if s["skill"] == "Logical reasoning")
    assert (logic["first"], logic["now"], logic["change"]) == (24, 88, "improved")
    assert (logic["first_result"], logic["latest_result"]) == ("level 2 of 5 · 2 of 5 right", "level 5 of 5 · 5 of 5 right")


def test_the_study_plan_only_for_jee_and_neet(db_session):
    asha = ready(db_session)
    assert "JEE and NEET" in execute_tool(db_session, asha, "exam_study_plan", {})["note"]


def test_every_reply_carries_the_roadmap(client, monkeypatch):
    token = register(client)
    llm = FakeLLM("Okay.")
    monkeypatch.setattr(orchestrator, "get_llm_provider", lambda: llm)
    client.post("/api/ai/chat", json={"message": "Mera next step kya hai?"}, headers={"Authorization": f"Bearer {token}"})
    assert NONE_YET in "\n".join(m["content"] for m in llm.seen[0] if m["role"] == "system")


def test_a_new_focus_can_leave_the_old_one_behind(db_session):
    from app.roadmap import service

    asha = ready(db_session)
    execute_tool(db_session, asha, "set_roadmap_focus", {"career": "AI"})
    out = execute_tool(db_session, asha, "set_roadmap_focus", {"career": "cybersecurity", "dropping": "AI"})
    assert (out["focus"], out["exploring"], out["moved_away_from"]) == (
        "Cybersecurity", [], ["Data Science & Artificial Intelligence"])
    execute_tool(db_session, asha, "adjust_roadmap", {"save": True, "kind": "difficulty", "subject": "maths"})
    focus, maths = service.versions(db_session, asha)[-2:]
    assert focus["rationale"]["en"] == "You chose a new focus: Cybersecurity, moving away from Data Science & Artificial Intelligence."
    assert focus["rationale"]["hi"] == "आपने नया लक्ष्य चुना: साइबर सुरक्षा, डेटा साइंस और आर्टिफ़िशियल इंटेलिजेंस से हटकर।"
    assert maths["rationale"]["hi"] == "आपने कहा कि मैथ्स मुश्किल लगता है।", "Hindi names in the Hindi note"


def test_a_change_is_shown_before_it_is_made(db_session):
    from app.roadmap import service

    asha = ready(db_session)
    execute_tool(db_session, asha, "set_roadmap_focus", {"career": "AI"})
    before = service.view(db_session, asha)
    preview = execute_tool(db_session, asha, "adjust_roadmap", {"kind": "difficulty", "subject": "maths", "save": False})
    assert preview["saved"] is False and preview["new_version"] is None and "NOT saved" in preview["note"]
    assert {"change": "add", "step": "Maths foundation", "reason": "Added because you said maths feels hard."} in preview["would_change"]
    swap = execute_tool(db_session, asha, "adjust_roadmap", {"kind": "focus", "career": "cybersecurity", "dropping": "AI"})
    assert swap["saved"] is False and swap["focus"] == "Cybersecurity", "save left out is a preview too"
    assert swap["moved_away_from"] == ["Data Science & Artificial Intelligence"]
    after = service.view(db_session, asha)
    assert (after["version"], after["focus"], after["difficulties"]) == (before["version"], before["focus"], []), "nothing changed"
    assert len(service.versions(db_session, asha)) == before["version"]

    made = execute_tool(db_session, asha, "adjust_roadmap", {"kind": "difficulty", "subject": "maths", "save": True})
    assert made["saved"] and made["new_version"] == before["version"] + 1
    assert [c["step"] for c in made["changes"]] == [c["step"] for c in preview["would_change"]], "what was shown is what's made"
