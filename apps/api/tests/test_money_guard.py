"""The money guard: MAYA says no rupee amount the conversation hasn't seen in a tool's result or the
student's own words — a sentence with an invented fee is replaced before it's spoken or shown."""

from datetime import datetime, timezone

from app.ai import orchestrator
from app.ai.money_guard import Guard, amounts
from app.facts import store
from tests.fakes import FakeLLM
from tests.test_assessment_api import auth
from tests.test_conversation_ws import register
from tests.test_discover import college


def test_amounts_as_people_write_them():
    assert amounts("Tuition is ₹62,500 a semester.") == [62500]
    assert amounts("Rs. 1.25 lakh a year, or about 2 lakh rupaye with the hostel") == [125000, 200000]
    assert amounts("do lakh ka budget hai") == [200000] and amounts("दो लाख") == [200000]
    assert amounts("₹ ४२,००० सालाना") == [42000] and amounts("a 1.5 crore package") == [15000000]
    assert amounts("rank 5000 in 2026; call 14416") == [], "ranks, years and phone numbers aren't money"


def test_the_guard_keeps_what_was_seen_and_replaces_the_rest():
    g = Guard(['{"value": "₹62,500 a semester", "amount": 62500}', "Mera budget 2 lakh hai"], "hinglish")
    said = g.feed("Tuition ₹62,500 a semester hai, yaani saal ka lagbhag ₹1.25 lakh. Hostel Rs. 45,000 hai. ")
    assert said[0] == "Tuition ₹62,500 a semester hai, yaani saal ka lagbhag ₹1.25 lakh. ", "per year from per semester"
    assert said[1] == "Iski verified amount mere paas nahi hai. "
    assert g.feed("Aapke 2 lakh ke budget mein aata hai.") == [] and g.flush() == "Aapke 2 lakh ke budget mein aata hai."
    assert g.replaced == ["Hostel Rs. 45,000 hai."]


def test_an_invented_fee_never_reaches_the_student(client, db_session, monkeypatch):
    manit = college(db_session, "Maulana Azad National Institute of Technology Bhopal", "Bhopal", "Madhya Pradesh", "JEE_MAIN")
    src = store.source(db_session, "site-manit", "MANIT Bhopal (official website)", 2)
    doc = store.document(db_session, src, "https://www.manit.ac.in/fees.pdf", "B.Tech fee structure 2026-27",
                         datetime(2026, 10, 1, tzinfo=timezone.utc), sha256="e" * 64)
    store.record(db_session, "college", manit.id, "fee.tuition.annual", {"amount": 62500, "per": "semester", "applies_to": "general"},
                 document=doc, academic_year="2026-27", quote="Tuition Fee 62500", now=datetime(2026, 10, 1, tzinfo=timezone.utc))
    db_session.commit()
    token = register(client)
    llm = FakeLLM([("college_facts", f'{{"college_id": {manit.id}, "topic": "fees"}}')],
                  "MANIT ki tuition ₹62,500 a semester hai, per its 2026-27 fee notice. Hostel ₹45,000 saal ka hai. Aur kuch?")
    monkeypatch.setattr(orchestrator, "get_llm_provider", lambda: llm)
    reply = client.post("/api/ai/chat", json={"message": "MANIT Bhopal ki fees kitni hai?"}, headers=auth(token)).json()["reply"]
    assert "₹62,500 a semester" in reply, "the fee from the tool is said"
    assert "45,000" not in reply and "Iski verified amount mere paas nahi hai." in reply, "the invented one is not"
    assert "Aur kuch?" in reply
    system = "\n".join(m["content"] for m in llm.seen[0] if m["role"] == "system")
    assert "never estimate a fee" in system and "Never call a college the best" in system


def test_find_colleges(db_session):
    from app.ai.tools import execute_tool
    from tests.test_assessment_service import student

    college(db_session, "Indian Institute of Technology Indore", "Indore", "Madhya Pradesh", "JEE_ADVANCED")
    asha = student(db_session)
    asha.city, asha.state = "Indore", "Madhya Pradesh"
    found = execute_tool(db_session, asha, "find_colleges", {"radius_km": 100})
    assert found["home"] == {"town": "Indore", "state": "Madhya Pradesh"} and found["sorted_by"] == "distance"
    assert found["colleges"][0]["name"] == "Indian Institute of Technology Indore" and found["colleges"][0]["distance_km"] < 30
    assert "left out" in found["note"]
    assert "error" in execute_tool(db_session, asha, "find_colleges", {"career": "astronaut"})
