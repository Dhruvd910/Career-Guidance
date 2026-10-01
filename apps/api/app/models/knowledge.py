"""The career knowledge graph (docs/design/04-knowledge-graph.md, 13-phase4-plan.md).

Nodes have stable typed keys — `career:cse`, `skill:python`, `degree:btech_cse`, `college:412` —
which the rest of MAYA refers to without foreign keys. Edges are typed (`requires_skill`,
`entered_through`, `offered_at`…) and unique per (source, type, destination).

Every node and edge records where it came from: `official` (JoSAA/MCC files, exam bulletins),
`curated` (editorial judgement, reviewed or not) or `derived` (computed from other data). The
graph is reference data: it's loaded whole from the canonical knowledge files and the official
tables, one version at a time (`kg_versions`).
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.types import Json


class KgNode(Base):
    __tablename__ = "kg_nodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(120), unique=True)
    type: Mapped[str] = mapped_column(String(30), index=True)  # career | skill | degree | college | …
    name: Mapped[dict] = mapped_column(Json)  # {"en": …, "hi": …}
    aliases: Mapped[list] = mapped_column(Json, default=list)  # other names people use
    attrs: Mapped[dict] = mapped_column(Json, default=dict)
    # {"kind": "official"|"curated"|"derived", "ref": "josaa_2026"|"maya_editorial_v1"|…, "url": …}
    source: Mapped[dict] = mapped_column(Json)
    # official | reviewed | unreviewed — curated knowledge stays "unreviewed" until a person signs it off
    review: Mapped[str] = mapped_column(String(20), default="unreviewed")


class KgEdge(Base):
    __tablename__ = "kg_edges"
    __table_args__ = (
        UniqueConstraint("src_key", "type", "dst_key", name="uq_kg_edge"),
        Index("ix_kg_edges_src_type", "src_key", "type"),
        Index("ix_kg_edges_dst_type", "dst_key", "type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    src_key: Mapped[str] = mapped_column(ForeignKey("kg_nodes.key", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(30))
    dst_key: Mapped[str] = mapped_column(ForeignKey("kg_nodes.key", ondelete="CASCADE"))
    attrs: Mapped[dict] = mapped_column(Json, default=dict)  # e.g. {"level": "intermediate"}
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[dict] = mapped_column(Json)
    review: Mapped[str] = mapped_column(String(20), default="unreviewed")


class KgVersion(Base):
    """One load of the graph: what it was built from, how big it is, what didn't match."""

    __tablename__ = "kg_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    counts: Mapped[dict] = mapped_column(Json, default=dict)  # {"nodes": {"career": 29, …}, "edges": {…}}
    # Official rows the graph couldn't place, e.g. a JoSAA branch no degree pattern matches.
    unmatched: Mapped[dict] = mapped_column(Json, default=dict)
    nodes: Mapped[int] = mapped_column(Integer, default=0)
    edges: Mapped[int] = mapped_column(Integer, default=0)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
