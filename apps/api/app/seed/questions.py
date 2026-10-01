"""Loads the practice question bank.

The questions are written for this app — they are not reproductions of past papers — so
they carry source/verification fields like every other factual table and are labelled as
practice content wherever they appear.

Run on its own with:  python -m app.seed.questions [--reset]
"""

import argparse
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.db import Base, SessionLocal, engine
from app.models.exam import Exam
from app.models.practice import Question, QuestionExam

BANK_FILES = ["questions_physics_chemistry.json", "questions_maths_biology.json"]
SOURCE = "Written for AI Career Guide practice papers (not a past exam paper)"


def load_bank() -> list[dict]:
    questions = []
    for name in BANK_FILES:
        with open(Path(__file__).parent / name) as f:
            questions.extend(json.load(f))
    return questions


def _validate(entries: list[dict]) -> None:
    """A wrong key or a missing option would silently mark students down."""
    for i, entry in enumerate(entries):
        where = f"question {i + 1} ({entry.get('stem', '')[:40]}…)"
        assert len(entry["options"]) == 4, f"{where}: needs exactly 4 options"
        assert 0 <= entry["correct_index"] < 4, f"{where}: correct_index out of range"
        assert len(set(entry["options"])) == 4, f"{where}: duplicate options"
        assert entry["exams"], f"{where}: not linked to any exam"
        assert entry["explanation"], f"{where}: no explanation"


def seed_questions(db: Session, reset: bool = False) -> int:
    entries = load_bank()
    _validate(entries)

    existing = db.query(Question).count()
    if existing and not reset:
        print(f"Question bank already has {existing} questions — pass --reset to reload.")
        return 0
    if existing:
        db.query(QuestionExam).delete()
        db.query(Question).delete()
        db.commit()

    exams_by_code = {e.code: e for e in db.query(Exam).all()}
    loaded = 0
    for entry in entries:
        question = Question(
            subject=entry["subject"],
            topic=entry.get("topic"),
            class_level=entry.get("class_level"),
            difficulty=entry.get("difficulty", "medium"),
            stem=entry["stem"],
            options=entry["options"],
            correct_index=entry["correct_index"],
            explanation=entry["explanation"],
            source=SOURCE,
            verification_status="practice_content",
        )
        db.add(question)
        db.flush()
        for code in entry["exams"]:
            exam = exams_by_code.get(code)
            if exam is not None:
                db.add(QuestionExam(question_id=question.id, exam_id=exam.id))
        loaded += 1

    db.commit()
    return loaded


def run(reset: bool = False) -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(Exam).first() is None:
            print("No exams in the database yet — run `python -m app.seed.seed` first.")
            return
        loaded = seed_questions(db, reset=reset)
        if loaded:
            by_subject: dict[str, int] = {}
            for (subject,) in db.query(Question.subject).all():
                by_subject[subject] = by_subject.get(subject, 0) + 1
            print(f"Loaded {loaded} practice questions: " +
                  ", ".join(f"{n} {s}" for s, n in sorted(by_subject.items())))
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Reload the bank from the JSON files.")
    run(reset=parser.parse_args().reset)
