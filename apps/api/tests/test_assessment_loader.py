"""Instrument files: validated before use, loaded once per version, never edited in place."""

import json

import pytest
from pydantic import ValidationError

from app.assessment import loader
from app.assessment.spec import Instrument
from app.models.assessment import AssessmentInstrument, AssessmentItem

T = {"en": "x", "hi": "क"}


def tiny(version=1, **changes):
    raw = {
        "key": "tiny", "version": version, "category": "interest", "title": {"en": "Tiny", "hi": "छोटा"},
        "about": T, "intro": T, "scoring_method": "weighted_options", "est_minutes": 1,
        "dimensions": {"maths": {"en": "maths", "hi": "गणित", "group": "subject"}},
        "items": [
            {"key": "q1", "type": "choice", "section": T, "prompt": {"en": "Maths?", "hi": "गणित?"},
             "options": [{"key": "yes", "label": {"en": "Yes", "hi": "हाँ"}, "weights": {"maths": 3}},
                         {"key": "no", "label": {"en": "No", "hi": "नहीं"}, "weights": {"maths": 0}}]},
            {"key": "q2", "type": "choice", "section": T, "prompt": T, "requires": {"q1": ["yes"]},
             "options": [{"key": "a", "label": T, "weights": {"maths": 1}}, {"key": "b", "label": T, "weights": {"maths": 2}}]},
        ],
    }
    raw.update(changes)
    return raw


@pytest.fixture()
def instruments(tmp_path, monkeypatch):
    """A folder of instrument files the loader reads instead of the real ones."""
    monkeypatch.setattr(loader, "INSTRUMENT_DIR", tmp_path)
    loader.all_versions.cache_clear()

    def write(raw):
        (tmp_path / f"{raw['key']}.v{raw['version']}.json").write_text(json.dumps(raw, ensure_ascii=False))
        loader.all_versions.cache_clear()

    yield write
    loader.all_versions.cache_clear()


def test_an_instrument_is_loaded_once_with_its_items(db_session, instruments):
    instruments(tiny())
    synced = loader.sync_instruments(db_session)
    assert synced["tiny"].version == 1
    assert [i.key for i in synced["tiny"].items] == ["q1", "q2"]
    assert synced["tiny"].items[1].content["requires"] == {"q1": ["yes"]}
    loader.sync_instruments(db_session)
    assert db_session.query(AssessmentInstrument).count() == 1 and db_session.query(AssessmentItem).count() == 2


def test_editing_a_version_in_use_is_refused(db_session, instruments):
    instruments(tiny())
    loader.sync_instruments(db_session)
    edited = tiny()
    edited["items"][0]["prompt"]["en"] = "Do you like maths?"
    instruments(edited)
    with pytest.raises(loader.InstrumentChanged, match="bump its version"):
        loader.sync_instruments(db_session)


def test_a_new_version_retires_the_old_one_but_keeps_it(db_session, instruments):
    instruments(tiny())
    loader.sync_instruments(db_session)
    instruments(tiny(version=2))
    synced = loader.sync_instruments(db_session)
    assert synced["tiny"].version == 2
    rows = {r.version: r.status for r in db_session.query(AssessmentInstrument)}
    assert rows == {1: "retired", 2: "active"}


def test_every_word_must_exist_in_english_and_hindi():
    raw = tiny()
    raw["items"][0]["prompt"] = {"en": "Maths?"}
    with pytest.raises(ValidationError, match="hi"):
        Instrument.model_validate(raw)


@pytest.mark.parametrize("break_it, message", [
    (lambda r: r["items"][1].update(requires={"q9": ["yes"]}), "isn't an earlier item"),
    (lambda r: r["items"][1].update(requires={"q1": ["maybe"]}), "unknown answers"),
    (lambda r: r["items"][0]["options"][0].update(weights={"physics": 3}), "unknown dimension"),
    (lambda r: r["items"].append(dict(r["items"][0])), "duplicate item keys"),
    (lambda r: r["items"].append({"key": "p", "type": "problem", "section": T, "prompt": T, "dimension": "maths",
                                  "difficulty": 1, "answer": "z",
                                  "options": [{"key": k, "label": T} for k in "abc"]}), "answer among them"),
])
def test_broken_files_are_refused(break_it, message):
    raw = tiny()
    break_it(raw)
    with pytest.raises(ValidationError, match=message):
        Instrument.model_validate(raw)


def test_the_file_name_must_match_its_version(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "INSTRUMENT_DIR", tmp_path)
    (tmp_path / "tiny.v2.json").write_text(json.dumps(tiny(version=1)))
    loader.all_versions.cache_clear()
    try:
        with pytest.raises(ValueError, match="should be named tiny.v1.json"):
            loader.all_versions()
    finally:
        loader.all_versions.cache_clear()


def test_the_real_instruments_match_their_lock():
    """Editing a released instrument without bumping its version fails here, before any student sees it."""
    lock = json.loads(loader.LOCK_FILE.read_text())
    files = {spec.ref: sha for spec, sha in loader.instrument_files().values()}
    assert files == lock, "instrument content changed: bump the version, then `python -m app.assessment.loader --lock`"
