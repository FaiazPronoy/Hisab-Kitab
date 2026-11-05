import uuid
from datetime import date, datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer,
    Numeric, String, Text, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBED_DIM = 384
Money = Numeric(18, 4)


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSONB, list: JSONB}


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    filename: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    storage_key: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20))  # pdf | image | sheet
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    pages_done: Mapped[int] = mapped_column(Integer, default=0)
    pages_failed: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    pages: Mapped[list["Page"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Page(Base):
    __tablename__ = "pages"

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    page_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str | None] = mapped_column(String(20))  # text_layer | ocr | vision | sheet
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str | None] = mapped_column(String(100))
    text: Mapped[str | None] = mapped_column(Text)
    layout: Mapped[str | None] = mapped_column(Text)  # line-numbered text sent to the LLM
    words: Mapped[list | None] = mapped_column(JSONB)
    lines: Mapped[dict | None] = mapped_column(JSONB)  # line_id -> bbox
    ocr_conf: Mapped[float | None] = mapped_column(Float)
    width: Mapped[float | None] = mapped_column(Float)
    height: Mapped[float | None] = mapped_column(Float)
    image_key: Mapped[str | None] = mapped_column(String(120))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    tsv: Mapped[str | None] = mapped_column(TSVECTOR)

    document: Mapped[Document] = relationship(back_populates="pages")


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    sheet_name: Mapped[str | None] = mapped_column(String(120))
    row_index: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="extracted")
    doc_type: Mapped[str] = mapped_column(String(20), default="invoice")  # invoice | credit_note | receipt
    invoice_number: Mapped[str | None] = mapped_column(String(100))
    invoice_number_norm: Mapped[str | None] = mapped_column(String(100))
    invoice_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    supplier_name: Mapped[str | None] = mapped_column(String(255))
    supplier_norm: Mapped[str | None] = mapped_column(String(255))
    customer_name: Mapped[str | None] = mapped_column(String(255))
    po_number: Mapped[str | None] = mapped_column(String(100))
    currency: Mapped[str | None] = mapped_column(String(3))
    subtotal: Mapped[Decimal | None] = mapped_column(Money)
    tax: Mapped[Decimal | None] = mapped_column(Money)
    discount: Mapped[Decimal | None] = mapped_column(Money)
    shipping: Mapped[Decimal | None] = mapped_column(Money)
    total: Mapped[Decimal | None] = mapped_column(Money)
    tax_lines: Mapped[list | None] = mapped_column(JSONB)
    overall_confidence: Mapped[float | None] = mapped_column(Float)
    boundary_confidence: Mapped[float | None] = mapped_column(Float)
    flags: Mapped[list | None] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=1)
    search_tsv: Mapped[str | None] = mapped_column(TSVECTOR)
    embedding = mapped_column(Vector(EMBED_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    document: Mapped[Document] = relationship(back_populates="invoices")
    fields: Mapped[list["ExtractedField"]] = relationship(cascade="all, delete-orphan")
    line_items: Mapped[list["LineItem"]] = relationship(cascade="all, delete-orphan", order_by="LineItem.idx")
    findings: Mapped[list["ValidationResult"]] = relationship(cascade="all, delete-orphan")

    __mapper_args__ = {"version_id_col": version}
    __table_args__ = (
        Index("ix_invoices_supplier_number", "supplier_norm", "invoice_number_norm"),
        Index("ix_invoices_review", "created_at", postgresql_where=text("status = 'needs_review'")),
        Index("ix_invoices_search", "search_tsv", postgresql_using="gin"),
        Index("ix_invoices_supplier_trgm", "supplier_norm", postgresql_using="gin",
              postgresql_ops={"supplier_norm": "gin_trgm_ops"}),
        Index("ix_invoices_number_trgm", "invoice_number_norm", postgresql_using="gin",
              postgresql_ops={"invoice_number_norm": "gin_trgm_ops"}),
        Index("ix_invoices_embedding", "embedding", postgresql_using="hnsw",
              postgresql_ops={"embedding": "vector_cosine_ops"}),
    )


class ExtractedField(Base):
    __tablename__ = "extracted_fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    value_raw: Mapped[str | None] = mapped_column(Text)
    value_norm: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    page_no: Mapped[int | None] = mapped_column(Integer)
    line_id: Mapped[str | None] = mapped_column(String(20))
    bbox: Mapped[list | None] = mapped_column(JSONB)
    evidence_quote: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(10), default="llm")  # rule | llm | vision | sheet | user
    null_reason: Mapped[str | None] = mapped_column(String(30))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)


class LineItem(Base):
    __tablename__ = "line_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal | None] = mapped_column(Money)
    unit_price: Mapped[Decimal | None] = mapped_column(Money)
    amount: Mapped[Decimal | None] = mapped_column(Money)
    tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    confidence: Mapped[float | None] = mapped_column(Float)
    evidence: Mapped[dict | None] = mapped_column(JSONB)


class ValidationResult(Base):
    __tablename__ = "validation_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    rule_code: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10))
    field: Mapped[str | None] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    expected: Mapped[str | None] = mapped_column(Text)
    actual: Mapped[str | None] = mapped_column(Text)
    related_invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Correction(Base):
    __tablename__ = "corrections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(String(60))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    corrected_by: Mapped[str] = mapped_column(String(100), default="reviewer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(20), default="process")
    queue: Mapped[str] = mapped_column(String(20), default="ingest")
    status: Mapped[str] = mapped_column(String(20), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProcessingEvent(Base):
    __tablename__ = "processing_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    page_no: Mapped[int | None] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FailedTask(Base):
    __tablename__ = "failed_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_name: Mapped[str] = mapped_column(String(100))
    args: Mapped[list | None] = mapped_column(JSONB)
    error: Mapped[str] = mapped_column(Text)
    traceback: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReconciliationRun(Base):
    __tablename__ = "reconciliation_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(20))  # ledger | duplicate_copy | po_match
    left_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    right_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    summary: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    items: Mapped[list["ReconciliationItem"]] = relationship(cascade="all, delete-orphan")


class ReconciliationItem(Base):
    __tablename__ = "reconciliation_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reconciliation_runs.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(30))
    field: Mapped[str | None] = mapped_column(String(40))
    left_value: Mapped[str | None] = mapped_column(Text)
    right_value: Mapped[str | None] = mapped_column(Text)
    delta: Mapped[str | None] = mapped_column(String(50))
    severity: Mapped[str] = mapped_column(String(10), default="info")
    left_ref: Mapped[dict | None] = mapped_column(JSONB)
    right_ref: Mapped[dict | None] = mapped_column(JSONB)


class LlmCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prompt_version: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(60))
    purpose: Mapped[str] = mapped_column(String(30))
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    response: Mapped[dict | None] = mapped_column(JSONB)  # cached structured output only
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


Index("ix_pages_tsv", Page.tsv, postgresql_using="gin")
