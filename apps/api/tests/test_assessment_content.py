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


def test_the_six_instruments_exist():
    assert set(instrument_files()) == {"interests", "aptitude", "skills", "coding_check", "academic", "spatial"}


@pytest.mark.parametrize("key", ["interests", "aptitude", "skills", "coding_check", "academic", "spatial"])
def test_hindi_is_written_in_hindi_and_never_as_a_gendered_slash(key):
    """MAYA reads these aloud: "करता/करती" would come out as nonsense."""
    for hi in hindi_texts(spec(key)):
        assert not re.search(r"\w/\w", hi), hi
    for hi in hindi_texts(spec(key), options=False):  # options can be numbers, names or code
        assert re.search(r"[ऀ-ॿ]", hi), f"no Devanagari: {hi}"


@pytest.mark.parametrize("key", ["aptitude", "spatial", "coding_check"])
def test_the_adaptive_banks_have_enough_at_every_level(key):
    """A student can stay at one level the whole way (always right, or always wrong), and three takes in a row
    shouldn't repeat a question: ten at every level of every dimension."""
    inst = spec(key)
    assert inst.adaptive is not None and inst.scoring_method == "adaptive_correct"
    shape = Counter((i.dimension, i.difficulty) for i in inst.items)
    for dim in inst.dimensions:
        for level in range(1, inst.adaptive.levels + 1):
            assert shape[(dim, level)] >= 10, (dim, level)
    assert inst.adaptive.start["6"] == 1 and inst.adaptive.start["12"] >= 2


def _run(code: str) -> dict:
    """The coding check's pseudo-code, run as Python."""
    import re as _re

    py = _re.sub(r"repeat for (\w+) = (\d+) to (\d+):", r"for \1 in range(\2, \3 + 1):", code)
    py = _re.sub(r"for each (\w+) in (\w+):", r"for \1 in \2:", py).replace("function f(n):", "def f(n):")
    scope: dict = {}
    exec(py, scope)  # noqa: S102 — our own generated questions (one namespace, so f can call itself)
    return scope


def test_every_code_question_is_marked_by_running_its_code():
    for item in spec("coding_check").items:
        if not item.code:
            continue
        var = re.search(r"What is (\w+) at the end", item.prompt.en).group(1)
        expected = next(o.label.en for o in item.options if o.key == item.answer)
        assert str(_run(item.code)[var]) == expected, item.key


@pytest.mark.parametrize("key", ["aptitude", "coding_check", "spatial"])
def test_every_problem_has_one_clear_answer(key):
    for item in spec(key).items:
        for lang in ("en", "hi"):
            labels = [getattr(o.label, lang) for o in item.options]
            assert len(labels) == len(set(labels)), f"{item.key}: two options read the same in {lang}"
        assert item.explanation is not None


@pytest.mark.parametrize("key", ["aptitude", "spatial", "coding_check"])
def test_answers_are_spread_over_the_options(key):
    """If B were always right, guessing B would look like ability."""
    items = spec(key).items
    answers = Counter(i.answer for i in items)
    assert len(answers) == 4 and max(answers.values()) <= 0.35 * len(items)


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


def test_the_spatial_puzzles_can_be_answered_by_voice():
    """Spec §8's spatial reasoning, as puzzles to picture, not pictures: one right answer each, every
    option distinct, and an explanation for reviewing afterwards."""
    puzzles = spec("spatial")
    assert puzzles.category == "aptitude" and len(puzzles.items) >= 50
    for item in puzzles.items:
        labels = [o.label.en for o in item.options]
        assert len(set(labels)) == 4 and item.answer in {o.key for o in item.options} and item.explanation, item.key
