"""Facts with provenance (docs/design/06-college-provenance.md, 15-phase6-plan.md).

Everything MAYA knows about a college from outside — a fee, a hostel, a health centre, where it
is, what's near it, when admissions open — is a fact: one attribute of one entity, with the
document it came from, where in that document, the words it was read from, when it was fetched
and checked, for which academic year, and how far to trust it. Unknown is a fact too
(`not_available`), so nothing is ever filled in.

A source is a publisher with a tier (spec §33: 1 government … 6 reputable secondary). A source
document is one fetch of one URL, kept with its sha256; a changed page is a new document.

These tables are loaded from the OKF bundle (app/okf/), which is the canonical form; nothing here
is edited by hand.
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.types import Embedding, Json

TIERS = {1: "government", 2: "institution", 3: "admission_portal", 4: "regulator", 5: "dataset", 6: "secondary"}
OFFICIAL_TIERS = (1, 2, 3, 4)
# verified: read from its document and checked · unverified: no checkable document (shown as
# "needs verification") · not_available: looked, not found · flagged: waiting for review, not
# shown · withdrawn: no longer in the OKF bundle (a reviewer rejected it, or its source dropped
# it), not shown. Disagreement between sources isn't a status: it's a FactConflict over the
# facts involved, which keep their own.
STATUSES = ("verified", "unverified", "not_available", "flagged", "withdrawn")
SHOWN = ("verified", "unverified", "not_available")


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(120), unique=True)  # "nirf", "josaa", "osm", "college:412"
    name: Mapped[str] = mapped_column(String(255))
    tier: Mapped[int] = mapped_column(Integer)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceDocument(Base):
    __tablename__ = "source_documents"
    __table_args__ = (Index("ix_source_documents_url", "url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    url: Mapped[str] = mapped_column(String(1000))
    title: Mapped[str] = mapped_column(String(500))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    storage_path: Mapped[str | None] = mapped_column(String(500), nullable=True)  # raw bytes, under data/sources/
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    academic_year: Mapped[str | None] = mapped_column(String(9), nullable=True)  # "2026-27"
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # pending | text | scanned | failed | reference (a citation we haven't fetched ourselves)
    parse_status: Mapped[str] = mapped_column(String(20), default="pending")
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    entity_refs: Mapped[list] = mapped_column(Json, default=list)  # ["college:412", "exam:3"]
    superseded_by: Mapped[int | None] = mapped_column(ForeignKey("source_documents.id"), nullable=True)

    source: Mapped[Source] = relationship()


class Fact(Base):
    __tablename__ = "facts"
    __table_args__ = (Index("ix_facts_entity_attribute", "entity_type", "entity_id", "attribute"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(20))  # college | exam
    entity_id: Mapped[int] = mapped_column(Integer)
    attribute: Mapped[str] = mapped_column(String(80))  # fee.hostel.annual, near.airport, …
    value: Mapped[dict | None] = mapped_column(Json, nullable=True)  # None when not_available
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    academic_year: Mapped[str | None] = mapped_column(String(9), nullable=True)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"), index=True)
    locator: Mapped[str | None] = mapped_column(String(300), nullable=True)  # "page 3, table 2"
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)  # the words it was read from
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[str] = mapped_column(String(30), default="auto")  # auto | human | migration
    status: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    flags: Mapped[list] = mapped_column(Json, default=list)  # why it waits for review
    superseded_by: Mapped[int | None] = mapped_column(ForeignKey("facts.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[SourceDocument] = relationship()


class FactConflict(Base):
    __tablename__ = "fact_conflicts"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[int] = mapped_column(Integer)
    attribute: Mapped[str] = mapped_column(String(80))
    academic_year: Mapped[str | None] = mapped_column(String(9), nullable=True)
    fact_ids: Mapped[list] = mapped_column(Json)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolution: Mapped[str] = mapped_column(String(20), default="unresolved")  # unresolved | agreed | picked
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)


class OkfLoad(Base):
    """One load of the OKF bundle into the database: which commit, what it held, what failed."""

    __tablename__ = "okf_loads"

    id: Mapped[int] = mapped_column(primary_key=True)
    commit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    concepts: Mapped[int] = mapped_column(Integer, default=0)
    facts: Mapped[int] = mapped_column(Integer, default=0)
    problems: Mapped[list] = mapped_column(Json, default=list)


class DocChunk(Base):
    """A passage of an official document, for searching by meaning and by words (doc 05)."""

    __tablename__ = "doc_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(500), nullable=True)  # its heading path
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    lang: Mapped[str] = mapped_column(String(10), default="en")
    entity_refs: Mapped[list] = mapped_column(Json, default=list)
    academic_year: Mapped[str | None] = mapped_column(String(9), nullable=True)
    embedding: Mapped[list | None] = mapped_column(Embedding(384), nullable=True)
    embed_model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    document: Mapped[SourceDocument] = relationship()
