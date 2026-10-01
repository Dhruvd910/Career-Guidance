"""The canonical knowledge format (spec §14): how a file in app/knowledge/graph/ is written, and
which node and edge types exist.

    source: {kind: curated, ref: maya_editorial_v1}
    nodes:
      - key: skill:python
        name: {en: Python, hi: पाइथन}
        attrs: {kind: technical, measured_by: [check:programming, skill:programming]}
        edges:
          skill_prerequisite: [skill:programming_fundamentals]
          developed_by:
            - project:marks_analysis
            - {to: course:cs50x, level: foundation}

A node's type is its key's prefix. An edge's extra fields become its attrs (`weight` is kept
apart). Sources are inherited — file → node → edge — unless one says otherwise.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

NODE_TYPES = {
    "career", "job_role", "industry", "domain", "skill", "subject", "stream", "degree", "course", "exam",
    "college", "city", "state", "certification", "project", "trait",
}
# edge type: (allowed source types, allowed destination types)
EDGE_TYPES: dict[str, tuple[set[str], set[str]]] = {
    "requires_skill": ({"career", "job_role", "degree"}, {"skill"}),
    "skill_prerequisite": ({"skill"}, {"skill"}),
    "developed_by": ({"skill"}, {"project", "certification", "course"}),
    "related_subject": ({"career", "degree", "skill"}, {"subject"}),
    "stream_includes": ({"stream"}, {"subject"}),
    "entered_through": ({"career"}, {"degree"}),
    "requires_subject": ({"degree"}, {"subject"}),
    "requires_exam": ({"degree", "career"}, {"exam"}),  # a career's own gate, e.g. UPSC for civil services
    "continues_to": ({"degree"}, {"degree"}),
    "offered_at": ({"degree"}, {"college"}),
    "part_of": ({"career"}, {"domain"}),
    "leads_to_role": ({"career"}, {"job_role"}),
    "works_in": ({"career"}, {"industry"}),
    "related_career": ({"career"}, {"career"}),
    "located_in": ({"college", "city"}, {"city", "state"}),
    "fits_trait": ({"career"}, {"trait"}),
}


class Name(BaseModel):
    # Unknown fields are an error, not ignored: in YAML's one-line form an unquoted comma splits a
    # name — {en: Civil Services (IAS, IPS, IFS)} — and the rest would otherwise vanish silently.
    model_config = ConfigDict(extra="forbid")

    en: str = Field(min_length=1)
    hi: str = Field(min_length=1)


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["official", "curated", "derived"]
    ref: str
    url: str | None = None
    academic_year: str | None = None

    @property
    def review(self) -> str:
        return "official" if self.kind == "official" else "unreviewed"


class EdgeSpec(BaseModel):
    to: str
    weight: float | None = None
    source: Source | None = None
    attrs: dict = {}


class NodeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z_]+:[A-Za-z0-9_]+$")
    name: Name
    aliases: list[str] = []
    attrs: dict = {}
    source: Source | None = None
    edges: dict[str, list[EdgeSpec]] = {}

    @property
    def type(self) -> str:
        return self.key.split(":", 1)[0]

    @field_validator("edges", mode="before")
    @classmethod
    def _edges(cls, raw):
        """`[skill:x, {to: skill:y, level: advanced}]` → EdgeSpecs, extra fields as attrs."""
        out = {}
        for edge_type, targets in (raw or {}).items():
            specs = []
            for target in targets or []:
                if isinstance(target, str):
                    specs.append({"to": target})
                else:
                    extra = {k: v for k, v in target.items() if k not in ("to", "weight", "source")}
                    specs.append({"to": target["to"], "weight": target.get("weight"), "source": target.get("source"),
                                  "attrs": extra})
            out[edge_type] = specs
        return out


class GraphFile(BaseModel):
    source: Source
    nodes: list[NodeSpec]
