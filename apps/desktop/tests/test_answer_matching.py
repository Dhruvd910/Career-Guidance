"""Spoken answers to assessment questions, in English, Hindi and Hinglish — matched on the Pi.

Uses the real instruments from the API, shaped the way the server sends items."""

import json
from pathlib import Path

import pytest

from app.answer_matching import match_answer, parse_number, wants_to_go_back, wants_to_skip

INSTRUMENTS = Path(__file__).resolve().parents[2] / "api" / "app" / "assessment" / "instruments"


def item(instrument: str, key: str) -> dict:
    spec = json.loads((INSTRUMENTS / f"{instrument}.v1.json").read_text())
    raw = next(i for i in spec["items"] if i["key"] == key)
    return {"key": raw["key"], "type": raw["type"],
            "options": [{"key": o["key"], "label": o["label"], "keywords": o.get("keywords", {})}
                        for o in raw.get("options", [])]}


MATHS = item("interests", "int_maths")


@pytest.mark.parametrize("said, option", [
    ("I love it", "love"),
    ("Maths is my favourite subject", "love"),
    ("mujhe maths bahut pasand hai", "love"),
    ("मुझे मैथ्स बहुत पसंद है", "love"),
    ("haan theek hai, pasand hai", "like"),
    ("nahi pasand, boring hai", "meh"),  # "nahi pasand" outranks "pasand"
    ("मुझे ज़्यादा नहीं", "meh"),
    ("मुझे ज्यादा नहीं", "meh"),  # without the nukta
    ("bahut mushkil lagta hai", "hard"),
    ("I struggle with it", "hard"),
    ("the second one", "like"),
    ("दूसरा वाला", "like"),
    ("option D", "hard"),
])
def test_interest_answers_in_three_languages(said, option):
    assert match_answer(said, MATHS) == {"option": option}


def test_choices_by_their_hindi_label():
    assert match_answer("सरकारी नौकरी", item("interests", "sector")) == {"option": "govt"}
    assert match_answer("sarkari naukri chahiye", item("interests", "sector")) == {"option": "govt"}
    assert match_answer("हाँ, बहुत", item("interests", "build_things")) == {"option": "yes"}
    assert match_answer("हां बहुत", item("interests", "build_things")) == {"option": "yes"}


@pytest.mark.parametrize("said, option", [
    ("Two", "l1"), ("the third one", "l2"), ("teesra", "l2"), ("चौथा", "l3"), ("pehla wala", "l0"),
    ("level 2", "l1"), ("I've never written code", "l0"), ("मैंने कभी कोड नहीं लिखा", "l0"),
])
def test_skill_levels_by_position_or_words(said, option):
    assert match_answer(said, item("skills", "programming")) == {"option": option}


@pytest.mark.parametrize("said, option", [
    ("60", "b"), ("sixty rupees", "b"), ("साठ", "b"), ("₹60", "b"), ("B", "b"), ("option b", "b"), ("बी", "b"),
])
def test_problem_answers_by_value_or_letter(said, option):
    assert match_answer(said, item("aptitude", "a_num_1")) == {"option": option}


def test_a_number_in_a_problem_is_the_answer_not_the_option_number():
    # Options are 10, 11, 12, 13: "11" is option B, not the eleventh option.
    assert match_answer("eleven", item("aptitude", "a_log_4")) == {"option": "b"}
    assert match_answer("saadhe chaar ghante", item("aptitude", "a_num_4")) == {"option": "b"}
    assert match_answer("four and a half hours", item("aptitude", "a_num_4")) == {"option": "b"}


def test_spelled_out_letters_and_words():
    assert match_answer("E P H", item("aptitude", "a_log_3")) == {"option": "a"}
    assert match_answer("Can't tell from this", item("aptitude", "a_log_2")) == {"option": "c"}
    assert match_answer("Sara", item("aptitude", "a_log_1")) == {"option": "c"}


@pytest.mark.parametrize("said, value", [
    ("87", 87.0), ("87.5 percent", 87.5), ("eighty seven", 87.0), ("सत्तासी प्रतिशत", 87.0),
    ("sattasi percent", 87.0), ("45 out of 50", 90.0), ("50 mein se 45", 90.0), ("I got ninety", 90.0),
    ("hundred", 100.0),
])
def test_marks(said, value):
    assert match_answer(said, item("academic", "jr_maths")) == {"value": value}
    assert parse_number(said) == value


def test_marks_out_of_range_or_missing():
    assert match_answer("I got 120", item("academic", "jr_maths")) is None
    assert match_answer("ye subject nahi hai, chhodo", item("academic", "jr_maths")) == {"skip": True}


@pytest.mark.parametrize("said", ["skip", "chhodo", "छोड़ो", "अगला सवाल", "pata nahi", "I don't know"])
def test_skipping(said):
    assert wants_to_skip(said)
    assert match_answer(said, item("aptitude", "a_num_1")) == {"skip": True}


@pytest.mark.parametrize("said, back", [
    ("go back", True), ("peeche jao", True), ("पीछे चलिए", True), ("pichla sawal", True), ("Previous, please", True),
    ("I want to come back to Delhi", False), ("wapas ghar jaana hai", False),
])
def test_going_back_only_as_the_whole_answer(said, back):
    assert wants_to_go_back(said) is back


def test_not_understood_is_none():
    assert match_answer("the weather is nice today", MATHS) is None
    assert match_answer("", MATHS) is None
    assert match_answer("thank you", MATHS) is None
