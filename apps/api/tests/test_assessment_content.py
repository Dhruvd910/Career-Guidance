"""The real instruments and career needs: complete, bilingual, balanced, and consistent with the
career library."""

import json
import re
from collections import Counter
from pathlib import Path

import pytest

from app.assessment.loader import instrument_files
from app.seed.careers import load_library

NEEDS = json.loads((Path(__file__).resolve().parents[1] / "app/assessment/career_needs.json").read_text())


def spec(key):
    return instrument_files()[key][0]


def all_dimensions():
    return {d for s, _ in instrument_files().values() for d in s.dimensions}


def hindi_texts(instrument, options=True):
    yield instrument.title.hi
    yield instrument.intro.hi
    for item in instrument.items:
        yield item.prompt.hi
        if item.speak:
            yield item.speak.hi
        for option in item.options if options else []:
            yield option.label.hi


def test_the_five_instruments_exist():
    assert set(instrument_files()) == {"interests", "aptitude", "skills", "coding_check", "academic"}


@pytest.mark.parametrize("key", ["interests", "aptitude", "skills", "coding_check", "academic"])
def test_hindi_is_written_in_hindi_and_never_as_a_gendered_slash(key):
    """MAYA reads these aloud: "करता/करती" would come out as nonsense."""
    for hi in hindi_texts(spec(key)):
        assert not re.search(r"\w/\w", hi), hi
    for hi in hindi_texts(spec(key), options=False):  # options can be numbers, names or code
        assert re.search(r"[ऀ-ॿ]", hi), f"no Devanagari: {hi}"


def test_the_aptitude_forms_are_parallel():
    aptitude = spec("aptitude")
    shape = {form: Counter((i.dimension, i.difficulty) for i in aptitude.items if i.form == form) for form in aptitude.forms}
    assert shape["A"] == shape["B"]
    assert sum(shape["A"].values()) == 15
    assert {d for d, _ in shape["A"]} == {"aptitude:numerical", "aptitude:logical", "aptitude:verbal"}


@pytest.mark.parametrize("key", ["aptitude", "coding_check"])
def test_every_problem_has_one_clear_answer(key):
    for item in spec(key).items:
        for lang in ("en", "hi"):
            labels = [getattr(o.label, lang) for o in item.options]
            assert len(labels) == len(set(labels)), f"{item.key}: two options read the same in {lang}"
        assert item.explanation is not None


def test_answers_are_spread_over_the_options():
    """If B were always right, guessing B would look like ability."""
    answers = Counter(i.answer for i in spec("aptitude").items)
    assert len(answers) >= 3 and max(answers.values()) <= 16


def test_skills_are_concrete_levels():
    for item in spec("skills").items:
        assert [o.level for o in item.options] == [0, 1, 2, 3]


def test_the_interest_dimensions_cover_every_career_profile():
    interests = set(spec("interests").dimensions)
    for career in load_library():
        assert set(career["profile"]) | set(career["must"]) <= interests, career["key"]


def test_every_career_has_needs_questions_and_a_domain():
    library = {c["key"]: c for c in load_library()}
    assert set(NEEDS["careers"]) == set(library)
    known = all_dimensions()
    for key, entry in NEEDS["careers"].items():
        assert entry["needs"], key
        for dim, weight in entry["needs"].items():
            assert dim in known, f"{key}: unknown dimension {dim}"
            assert weight in (1, 2, 3)
        assert len(entry["ask_yourself"]) == 2 and all(q["en"] and q["hi"] for q in entry["ask_yourself"])
        assert library[key]["category"] in NEEDS["domains"]
