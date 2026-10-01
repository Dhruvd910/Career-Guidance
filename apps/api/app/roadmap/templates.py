"""Loading and checking the stage templates (templates.yaml) — every word in English and Hindi,
every slot one the generator knows, and nothing silently dropped by YAML (unknown fields are
errors: an unquoted comma in a one-line {en: …, hi: …} would otherwise cut text short)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

TEMPLATES = Path(__file__).parent / "templates.yaml"
SLOTS = {
    "assessments", "subject_foundation", "projects", "career_exploration", "stream_choice", "foundation_skills",
    "curiosity", "planning", "career_decision", "entrance_exams", "degree_selection", "college_exploration",
    "skill_development", "weak_areas", "skill_gap_analysis", "roles", "advanced_skills", "specialise",
}


class Text(BaseModel):
    model_config = ConfigDict(extra="forbid")

    en: str = Field(min_length=1)
    hi: str = Field(min_length=1)


class Milestone(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z_0-9]+$")
    title: Text
    why: Text | None = None
    done_when: Text | None = None
    slot: str | None = None
    subject_skill: str | None = None
    optional: bool = False
    exam_critical: bool = False
    hours: float | None = None

    @model_validator(mode="after")
    def _slot(self) -> "Milestone":
        if self.slot is not None and self.slot not in SLOTS:
            raise ValueError(f"{self.key}: unknown slot '{self.slot}'")
        if self.slot == "subject_foundation" and not self.subject_skill:
            raise ValueError(f"{self.key}: subject_foundation needs subject_skill")
        if self.slot is None and not (self.done_when and self.hours):
            raise ValueError(f"{self.key}: a milestone without a slot needs done_when and hours")
        return self


class Band(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classes: list[int] = []
    stages: list[str] = []
    later: list[str]
    spine: list[Milestone]


class Templates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    stages: dict[str, Text]
    bands: dict[str, Band]
    later: dict[str, list[Milestone]]

    @model_validator(mode="after")
    def _stages(self) -> "Templates":
        for name, band in self.bands.items():
            for stage in band.later + band.stages:
                if stage not in self.stages:
                    raise ValueError(f"band {name}: unknown stage {stage}")
        for stage in self.later:
            if stage not in self.stages:
                raise ValueError(f"later: unknown stage {stage}")
        return self


@lru_cache(maxsize=1)
def templates() -> Templates:
    return Templates.model_validate(yaml.safe_load(TEMPLATES.read_text()))
