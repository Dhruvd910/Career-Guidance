"""The real knowledge graph: valid, complete enough to answer the spec's questions, and matching
the real official programme names the way it was reviewed."""

import json
import re
from collections import defaultdict
from pathlib import Path

import pytest

from app.knowledge.loader import _programme_matcher, build

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "official_programme_degrees.json").read_text())


@pytest.fixture(scope="module")
def snap():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.core.db import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        yield build(db)


def edges(snap, edge_type):
    out = defaultdict(list)
    for (src, t, dst), e in snap.edges.items():
        if t == edge_type:
            out[src].append((dst, e))
    return out


def test_it_builds_and_validates(snap):
    types = {n["type"] for n in snap.nodes.values()}
    assert {"career", "skill", "degree", "exam", "subject", "stream", "domain", "project", "trait"} <= types


def test_every_career_has_a_common_route_and_a_main_domain(snap):
    routes, domains = edges(snap, "entered_through"), edges(snap, "part_of")
    for key, node in snap.nodes.items():
        if node["type"] == "career":
            assert any(e["attrs"].get("commonness") == "common" for _d, e in routes[key]), key
            assert domains[key], key


def test_the_spec_s_technology_domain(snap):
    """Spec §11's example tree: Technology → software, AI/data, cybersecurity, robotics, product design."""
    in_tech = {src for src, targets in edges(snap, "part_of").items() if any(d == "domain:technology" for d, _ in targets)}
    assert in_tech == {"career:cse", "career:ai_data", "career:cybersecurity", "career:robotics", "career:design"}


def test_every_requires_skill_has_level_and_importance(snap):
    for src, targets in edges(snap, "requires_skill").items():
        for dst, e in targets:
            assert e["attrs"]["level"] in ("foundation", "intermediate", "advanced"), (src, dst)
            assert 0 < e["attrs"]["importance"] <= 1, (src, dst)


def test_every_skill_can_be_developed(snap):
    developed = edges(snap, "developed_by")
    for key, node in snap.nodes.items():
        if node["type"] == "skill":
            assert developed[key], f"{key}: nothing develops it"


def test_curated_names_are_in_hindi(snap):
    for key, node in snap.nodes.items():
        if node["source"]["kind"] == "curated" or node["type"] in ("skill", "degree", "career", "domain"):
            assert re.search(r"[ऀ-ॿ]", node["name"]["hi"]), key


def test_every_edge_says_where_it_came_from(snap):
    for key, e in snap.edges.items():
        assert e["source"]["kind"] in ("official", "curated", "derived") and e["source"]["ref"], key
        assert e["review"] == ("official" if e["source"]["kind"] == "official" else "unreviewed"), key


def test_the_official_programme_names_map_as_reviewed(snap):
    match = _programme_matcher(snap)
    moved = [(p["course"], p["branch"], p["degree"], match(p["course"], p["branch"])) for p in FIXTURE["programmes"]
             if match(p["course"], p["branch"]) != p["degree"]]
    assert moved == [], "a pattern change moved these — review, then refresh the fixture"
    assert all(match(p["course"], p["branch"]) for p in FIXTURE["programmes"]), "every official programme has a degree"


def test_no_name_is_cut_short_by_a_comma():
    """In YAML's one-line form, {en: Civil Services (IAS, IPS, IFS)} silently becomes "Civil Services (IAS"."""
    import yaml

    from app.knowledge.loader import GRAPH_DIR

    for path in GRAPH_DIR.glob("*.yaml"):
        for node in yaml.safe_load(path.read_text())["nodes"]:
            assert set(node["name"]) == {"en", "hi"}, (path.name, node["key"], node["name"])
            assert node["name"]["en"].count("(") == node["name"]["en"].count(")"), node["key"]
