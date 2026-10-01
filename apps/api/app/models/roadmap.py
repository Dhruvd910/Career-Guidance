"""The student's roadmap and progress (spec §18–20, docs/design/09-roadmap-model.md, 14-phase5-plan.md).

A roadmap is one per student, with a focus career and any exploration branches. Each change makes
a new **version** — an immutable tree of nodes (stage → milestone → module → task) with the
trigger, the reasons and the inputs it was built from. **Progress is kept per node key**, not
per version, so what was finished stays finished whatever changes later.

Skill progress over time comes only from measurements (assessments, practice papers) — never from
the student ticking a module done, which is progress on the roadmap, not a skill level.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.types import Json
from app.models.mixins import TimestampMixin

DEFAULT_HOURS_PER_WEEK = 4


class Roadmap(Base, TimestampMixin):
    __tablename__ = "roadmaps"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"), unique=True)
    focus_career: Mapped[str | None] = mapped_column(String(80), nullable=True)  # "ai_data"; None while exploring
    branches: Mapped[list] = mapped_column(Json, default=list)  # careers being explored alongside: ["cybersecurity"]
    dropped: Mapped[list] = mapped_column(Json, default=list)  # careers the student moved away from
    hours_per_week: Mapped[int] = mapped_column(Integer, default=DEFAULT_HOURS_PER_WEEK)  # on top of school
    # Subjects the student finds hard ("mathematics") — each gets a foundation module.
    difficulties: Mapped[list] = mapped_column(Json, default=list)
    active_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    versions: Mapped[list["RoadmapVersion"]] = relationship(
        back_populates="roadmap", cascade="all, delete-orphan", order_by="RoadmapVersion.version_no")


class RoadmapVersion(Base):
    """One version of the whole tree. Never edited after it's written."""

    __tablename__ = "roadmap_versions"
    __table_args__ = (UniqueConstraint("roadmap_id", "version_no", name="uq_roadmap_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    roadmap_id: Mapped[int] = mapped_column(ForeignKey("roadmaps.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    parent_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trigger: Mapped[dict] = mapped_column(Json)  # {"kind": "time_budget", "detail": "2 hours a day"}
    rationale: Mapped[dict] = mapped_column(Json)  # {"en": …, "hi": …}
    inputs_snapshot: Mapped[dict] = mapped_column(Json)  # what it was built from — spec §18's inputs
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    roadmap: Mapped["Roadmap"] = relationship(back_populates="versions")
    nodes: Mapped[list["RoadmapNode"]] = relationship(
        back_populates="version", cascade="all, delete-orphan", order_by="RoadmapNode.sort")
    changes: Mapped[list["RoadmapChange"]] = relationship(
        back_populates="version", cascade="all, delete-orphan", order_by="RoadmapChange.id")


class RoadmapNode(Base):
    __tablename__ = "roadmap_nodes"
    __table_args__ = (UniqueConstraint("version_id", "node_key", name="uq_roadmap_node"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("roadmap_versions.id"), index=True)
    node_key: Mapped[str] = mapped_column(String(160))  # stable across versions: "module:skill:python"
    parent_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))  # stage | milestone | module | task | branch
    stage: Mapped[str] = mapped_column(String(30))  # class_10 | class_11 | degree | internship | career …
    title: Mapped[dict] = mapped_column(Json)
    detail: Mapped[dict] = mapped_column(Json, default=dict)  # {why, how, done_when, resources} in en/hi
    prerequisites: Mapped[list] = mapped_column(Json, default=list)  # node keys
    est_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    window: Mapped[dict | None] = mapped_column(Json, nullable=True)  # {"from": "2026-10", "to": "2026-12"}
    kg_refs: Mapped[list] = mapped_column(Json, default=list)  # ["skill:python", "career:ai_data"]
    state: Mapped[str] = mapped_column(String(20), default="active")  # active | deferred | parked
    attrs: Mapped[dict] = mapped_column(Json, default=dict)  # {"optional": true, "exam_critical": true, …}
    sort: Mapped[int] = mapped_column(Integer, default=0)

    version: Mapped["RoadmapVersion"] = relationship(back_populates="nodes")


class RoadmapProgress(Base):
    """How far the student is with one node — kept by node key, so it survives new versions."""

    __tablename__ = "roadmap_progress"

    roadmap_id: Mapped[int] = mapped_column(ForeignKey("roadmaps.id"), primary_key=True)
    node_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="not_started")  # not_started | in_progress | done | skipped
    percent: Mapped[int] = mapped_column(Integer, default=0)
    # [{"kind": "self"|"assessment"|"practice", "note": …, "at": …, "ref": …}] — newest last
    evidence: Mapped[list] = mapped_column(Json, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RoadmapChange(Base):
    """One change a version made, and why — what "What changed" shows."""

    __tablename__ = "roadmap_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("roadmap_versions.id"), index=True)
    op: Mapped[str] = mapped_column(String(20))  # add | remove | modify | defer | park | resume | done
    node_key: Mapped[str] = mapped_column(String(160))
    before: Mapped[dict | None] = mapped_column(Json, nullable=True)
    after: Mapped[dict | None] = mapped_column(Json, nullable=True)
    reason: Mapped[dict] = mapped_column(Json)  # {"en": …, "hi": …}

    version: Mapped["RoadmapVersion"] = relationship(back_populates="changes")


class SkillMeasurement(Base):
    """A skill's measured level at one moment (spec §20) — from an assessment or a practice paper."""

    __tablename__ = "skill_measurements"
    __table_args__ = (UniqueConstraint("student_profile_id", "skill_key", "source_kind", "source_id",
                                       name="uq_skill_measurement"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"), index=True)
    skill_key: Mapped[str] = mapped_column(String(80))  # a graph skill: "skill:programming_fundamentals"
    value: Mapped[float] = mapped_column(Float)  # 0–1
    source_kind: Mapped[str] = mapped_column(String(20))  # assessment | practice
    source_id: Mapped[str] = mapped_column(String(40))  # attempt id
    detail: Mapped[dict] = mapped_column(Json, default=dict)  # {"says": {"en": "5 of 8 right", …}, "dimension": …}
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
