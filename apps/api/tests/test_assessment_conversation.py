"""MAYA and the assessments: what she knows in every reply, her tools, and offering one on screen."""

import json

from app.ai import orchestrator
from app.ai.tools import TOOL_SPECS, execute_tool
from app.assessment.context import NONE_YET, assessment_context
from app.models.student import StudentProfile
from app.seed.careers import seed_careers
from tests.fakes import FakeLLM
from tests.test_assessment_service import right, student, take
from tests.test_career_directions import TECH, answers
from tests.test_conversation_ws import connect, register, services, until  # noqa: F401 — fixture


def system_text(llm):
    return "\n".join(m["content"] for m in llm.seen[0] if m["role"] == "system")


def test_the_old_guessing_tool_is_gone():
    names = {t["function"]["name"] for t in TOOL_SPECS}
    assert "assess_career_fit" not in names
    assert {"get_my_assessments", "explain_direction", "compare_assessments", "suggest_assessment"} <= names


def test_without_assessments_maya_offers_one_instead_of_guessing(db_session):
    asha = student(db_session)
    assert assessment_context(db_session, asha) == NONE_YET


def test_every_reply_knows_the_results_even_without_the_memory_permission(db_session):
    seed_careers(db_session)
    asha = student(db_session, memory=False)
    take(db_session, asha, "interests", answers(TECH))
    take(db_session, asha, "aptitude", choose=lambda i: right(i, wrong={"a_verb_1"}))
    text = assessment_context(db_session, asha)
    lines = text.splitlines()
    assert lines[1].startswith("- Career directions — strong alignment: ")
    assert "Computer Science & Software Engineering" in lines[1]
    assert "- What you enjoy [interests] (today): enjoys maths, computers and coding" in text
    assert "; matters to them: earning well" in text
    assert "- Thinking skills [aptitude] (today): " in text and "understanding words 4 of 5 right" in text
    assert lines[-1].startswith("- Not taken yet: ") and "Your skills" in lines[-1]
    assert len(text) <= 1400


def test_an_unfinished_one_is_mentioned(db_session):
    from app.assessment import service

    asha = student(db_session)
    view = service.start(db_session, asha, "skills")
    service.answer(db_session, asha, view["attempt_id"], "programming", {"option": "l1"})
    assert "Unfinished: Your skills, 1 answered" in assessment_context(db_session, asha)


def test_the_tools(db_session):
    seed_careers(db_session)
    asha = student(db_session)
    take(db_session, asha, "interests", answers(TECH))
    mine = execute_tool(db_session, asha, "get_my_assessments", {})
    assert "interests" in mine["results"] and "aptitude" in mine["not_taken"]
    assert {"career_key": "cse", "name": "Computer Science & Software Engineering", "band": "strong"} \
        in mine["directions"]["strong"]
    why = execute_tool(db_session, asha, "explain_direction", {"career_key": "cse"})
    assert why["band"] == "strong" and why["why"] and "evidence" not in why
    assert "error" in execute_tool(db_session, asha, "explain_direction", {"career_key": "astronaut"})
    one = execute_tool(db_session, asha, "compare_assessments", {})
    assert one["compared"] == {} and one["taken_once"] == ["interests"] and "taken twice" in one["note"]


def test_how_much_have_i_improved(db_session):
    asha = student(db_session)
    take(db_session, asha, "aptitude", choose=lambda i: right(i, wrong={"a_num_1", "a_num_2", "a_num_3"}))
    take(db_session, asha, "aptitude", choose=right)
    take(db_session, asha, "skills")  # taken once: nothing to compare there
    out = execute_tool(db_session, asha, "compare_assessments", {})  # without a key: everything retaken
    assert set(out["compared"]) == {"aptitude"}
    rows = out["compared"]["aptitude"]["since_previous"]
    numbers = next(r for r in rows if r["dimension"] == "working with numbers")
    assert numbers == {"dimension": "working with numbers", "before": "2 of 5 right", "after": "5 of 5 right",
                       "change": 1, "note": None}
    assert next(r for r in rows if r["dimension"] == "understanding words")["change"] == 0
    assert "taken 2 times — compare_assessments shows the change" in assessment_context(db_session, asha)


def test_offering_an_assessment_puts_a_button_on_screen(client, db_session, services):
    token = register(client)
    services["llm"] = FakeLLM(
        [("suggest_assessment", json.dumps({"instrument_key": "aptitude", "reason": "to see how you reason"}))],
        "Chalo ek chhota sa thinking skills check karte hain, das minute lagenge.")
    with connect(client, token) as ws:
        ws.receive_json()
        ws.send_json({"type": "turn.text", "turn_id": "t1", "text": "Mujhe nahi pata main kis cheez mein accha hoon"})
        seen = until(ws, "reply.done")
    suggestion = next(m for m in seen if m["type"] == "ui.suggest")
    assert suggestion["action"] == "open_assessment" and suggestion["instrument_key"] == "aptitude"
    assert suggestion["title"]["hi"] == "सोचने की क्षमता" and suggestion["est_minutes"] == 10
    tool_reply = next(m for m in services["llm"].seen[1] if m["role"] == "tool")
    assert '"ui"' not in tool_reply["content"] and "Thinking skills" in tool_reply["content"]
    assert NONE_YET in system_text(services["llm"])


def test_typed_chat_returns_the_suggestion_too(client, monkeypatch):
    token = register(client)
    llm = FakeLLM([("suggest_assessment", '{"instrument_key": "interests"}')], "Let's start with what you enjoy.")
    monkeypatch.setattr(orchestrator, "get_llm_provider", lambda: llm)
    out = client.post("/api/ai/chat", json={"message": "Which career suits me?"},
                      headers={"Authorization": f"Bearer {token}"}).json()
    assert out["suggestions"][0]["instrument_key"] == "interests"
    assert out["reply"] == "Let's start with what you enjoy."
