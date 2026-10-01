"""How an instrument file is written (app/assessment/instruments/*.json), and the checks every
file must pass before a student ever sees it.

Every word a student reads or hears exists in English and Hindi. An item is one of:

- `choice`   — options that add points to dimensions (interests): "I love maths" → maths +3;
               elsewhere a plain question whose answer steers what comes next (your stream)
- `anchored` — "which is most like you", levels 0–3 with concrete descriptions (skills)
- `problem`  — one right answer (aptitude, the coding check)
- `marks`    — a number 0–100 (the academic profile)
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class Text(BaseModel):
    en: str = Field(min_length=1)
    hi: str = Field(min_length=1)


class Keywords(BaseModel):
    """What a student might say for this option, by language — matched on the Pi."""

    en: list[str] = []
    hi: list[str] = []  # Devanagari
    hinglish: list[str] = []  # Hindi in Roman letters


class Option(BaseModel):
    key: str
    label: Text
    keywords: Keywords = Keywords()
    weights: dict[str, float] = {}  # choice
    level: int | None = Field(default=None, ge=0, le=3)  # anchored


class AppliesTo(BaseModel):
    """Only for some students — the academic profile asks about the subjects they actually take."""

    class_levels: list[int] | None = None
    streams: list[str] | None = None  # PCM | PCB | PCMB | commerce | humanities; None = any


class Item(BaseModel):
    key: str
    type: Literal["choice", "anchored", "problem", "marks"]
    section: Text
    prompt: Text
    speak: Text | None = None  # what MAYA says, when it differs from the prompt
    code: str | None = None  # a few lines of pseudo-code, shown as written (the coding check)
    options: list[Option] = []
    dimension: str | None = None  # anchored | problem | marks: the one dimension it measures
    answer: str | None = None  # problem: the right option's key
    explanation: Text | None = None  # problem: why, for reviewing afterwards
    requires: dict[str, list[str]] = {}  # earlier item key → answers that make this one apply
    applies_to: AppliesTo | None = None
    form: str | None = None
    difficulty: int | None = Field(default=None, ge=1, le=3)

    @model_validator(mode="after")
    def _shape(self) -> "Item":
        keys = [o.key for o in self.options]
        if len(keys) != len(set(keys)):
            raise ValueError(f"{self.key}: duplicate option keys")
        if self.type == "choice":
            if len(self.options) < 2:
                raise ValueError(f"{self.key}: a choice item needs 2+ options")
        elif self.type == "anchored":
            if not self.dimension or sorted(o.level for o in self.options) != list(range(len(self.options))):
                raise ValueError(f"{self.key}: an anchored item needs a dimension and levels 0..n-1")
        elif self.type == "problem":
            if not self.dimension or self.answer not in keys or len(self.options) < 3 or self.difficulty is None:
                raise ValueError(f"{self.key}: a problem needs a dimension, a difficulty, 3+ options and an answer among them")
        elif self.type == "marks":
            if not self.dimension or self.options:
                raise ValueError(f"{self.key}: a marks item needs a dimension and no options")
        return self


class Dimension(BaseModel):
    """How a dimension reads in a sentence, and which group it belongs to."""

    en: str
    hi: str
    group: str  # subject | riasec | work_style | values | learning | aptitude | skill | academic


class Instrument(BaseModel):
    key: str = Field(pattern=r"^[a-z_]+$")
    version: int = Field(ge=1)
    category: Literal["interest", "aptitude", "skill", "academic"]
    title: Text
    about: Text  # one line on the assessment's own screen
    intro: Text  # what MAYA says before the first question
    scoring_method: Literal["weighted_options", "correct_answers", "anchored_levels", "marks"]
    est_minutes: int
    forms: list[str] = []
    dimensions: dict[str, Dimension]
    items: list[Item]

    @field_validator("items")
    @classmethod
    def _unique(cls, items: list[Item]) -> list[Item]:
        keys = [i.key for i in items]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate item keys")
        return items

    @model_validator(mode="after")
    def _consistent(self) -> "Instrument":
        seen: dict[str, Item] = {}
        for item in self.items:
            for dim in [item.dimension, *(d for o in item.options for d in o.weights)]:
                if dim is not None and dim not in self.dimensions:
                    raise ValueError(f"{item.key}: unknown dimension '{dim}'")
            for earlier, answers in item.requires.items():
                if earlier not in seen:
                    raise ValueError(f"{item.key}: requires '{earlier}', which isn't an earlier item")
                unknown = set(answers) - {o.key for o in seen[earlier].options}
                if unknown:
                    raise ValueError(f"{item.key}: requires unknown answers {unknown} of '{earlier}'")
            if self.forms and item.form not in self.forms:
                raise ValueError(f"{item.key}: form must be one of {self.forms}")
            if self.scoring_method == "weighted_options" and any(not o.weights for o in item.options):
                raise ValueError(f"{item.key}: every option needs weights")
            seen[item.key] = item
        return self

    @property
    def ref(self) -> str:
        return f"{self.key}@{self.version}"
