"""Learn: a checked video for each topic (English and Hindi), a YouTube search for more, and a career's
topics in learning order — for the Learn screen, career guides, roadmap steps and MAYA."""

import json
import re
from pathlib import Path

from app.ai.tools import execute_tool
from app.knowledge import learning
from app.knowledge.graph_store import graph
from tests.test_assessment_service import student

VIDEOS = json.loads((Path(__file__).resolve().parents[1] / "app/knowledge/videos.json").read_text())["skills"]


def test_every_skill_has_videos_or_at_least_a_search(db_session):
    skills = {n["key"] for n in graph(db_session).of_type("skill")}
    assert skills <= set(VIDEOS), f"no entry for {sorted(skills - set(VIDEOS))[:5]}"
    with_videos = [k for k, e in VIDEOS.items() if e["videos"]]
    assert len(with_videos) >= 0.9 * len(skills)
    for key, entry in VIDEOS.items():
        assert entry["query"]["en"] and entry["query"]["hi"], key
        for v in entry["videos"]:
            assert v["lang"] in ("en", "hi") and re.fullmatch(r"[\w-]{11}", v["id"]) and v["title"] and v["channel"] and v["checked"], key
        assert len({v["id"] for v in entry["videos"]}) == len(entry["videos"]), f"{key}: the same video twice"


def test_a_topic_comes_with_watch_links_and_a_search():
    python = learning.for_skill("skill:python", "Python")
    assert {v["lang"] for v in python["videos"]} == {"en", "hi"}
    assert all(v["url"].startswith("https://www.youtube.com/watch?v=") for v in python["videos"])
    assert python["search"]["hi"].startswith("https://www.youtube.com/results?search_query=") and "hindi" in python["search"]["hi"]
    unknown = learning.for_skill("skill:juggling", "Juggling")
    assert unknown["videos"] == [] and "Juggling" in unknown["search"]["en"], "a search still works for anything"


def test_the_learn_screen_follows_the_focus_or_the_strongest_match(client, db_session):
    token = client.post("/api/auth/register", json={"email": "l@example.com", "password": "password123", "name": "L",
                                                     "class_level": 10}).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}
    nothing = client.get("/api/learn", headers=auth).json()
    assert nothing["career"] is None and nothing["why"] == "none" and nothing["careers"], "no focus, no tests: pick one"
    ai = client.get("/api/learn", params={"career": "data science"}, headers=auth).json()
    assert ai["career"]["key"] == "ai_data" and ai["why"] == "asked"
    order = [s["skill"] for s in ai["steps"]]
    assert order.index("skill:school_mathematics") < order.index("skill:machine_learning"), "foundations first"
    python = next(s for s in ai["steps"] if s["skill"] == "skill:python")
    assert python["videos"] and python["status"] == "not_measured" and python["for_career"]
    assert client.get("/api/learn/skill/python", headers=auth).json()["videos"]
    assert client.get("/api/learn/skill/juggling", headers=auth).status_code == 404


def test_maya_names_the_videos_and_offers_them_on_screen(db_session):
    asha = student(db_session)
    topic = execute_tool(db_session, asha, "learning_videos", {"topic": "Python kahan se seekhu"})
    assert topic["topic"] == "Python" and {v["lang"] for v in topic["videos"]} == {"en", "hi"}
    assert "url" not in json.dumps(topic["videos"]), "no web addresses for her to read aloud"
    assert topic["ui"]["action"] == "open_learn" and topic["ui"]["skill"] == "skill:python"
    maths = execute_tool(db_session, asha, "learning_videos", {"topic": "ganit"})
    assert maths["topic"] == "School mathematics", "a subject is learnt as its skill"
    career = execute_tool(db_session, asha, "learning_videos", {"career": "doctor"})
    assert career["career"] == "Doctor (MBBS)" and career["learn_in_order"] and career["ui"]["career"] == "mbbs"
    assert "error" in execute_tool(db_session, asha, "learning_videos", {"topic": "juggling"})
