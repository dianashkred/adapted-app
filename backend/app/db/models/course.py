import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (BigInteger, CheckConstraint, DateTime, ForeignKey, Identity, Index, Integer,
                        SmallInteger, String, Text, UniqueConstraint, text)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin
from app.db.enums import CourseVisibility, DocumentStatus, pg_enum

EMBEDDING_DIM = 384
MAX_FILE_BYTES = 50 * 1024 * 1024
ALLOWED_MIME = ("application/pdf",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "text/plain", "text/markdown")


class Course(CreatedAtMixin, Base):
    __tablename__ = "course"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    owner_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("account.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    language: Mapped[str] = mapped_column(String(10), server_default=text("'en'"))
    visibility: Mapped[CourseVisibility] = mapped_column(
        pg_enum(CourseVisibility, "course_visibility"), server_default=CourseVisibility.PRIVATE.value)

    __table_args__ = (
        CheckConstraint("length(btrim(title)) > 0", name="title_not_blank"),
        CheckConstraint("owner_account_id IS NOT NULL OR visibility = 'shared'", name="private_course_has_owner"),
    )


class Document(Base):
    __tablename__ = "document"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("course.id", ondelete="CASCADE"), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str | None] = mapped_column(String(500), unique=True)
    status: Mapped[DocumentStatus] = mapped_column(
        pg_enum(DocumentStatus, "document_status"), server_default=DocumentStatus.PROCESSING.value)
    error_message: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("course_id", "sha256", name="uq_document_course_file"),
        CheckConstraint(f"size_bytes > 0 AND size_bytes <= {MAX_FILE_BYTES}", name="size_limit"),
        CheckConstraint("mime_type IN (" + ", ".join(f"'{m}'" for m in ALLOWED_MIME) + ")", name="allowed_mime"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        CheckConstraint("status <> 'failed' OR error_message IS NOT NULL", name="failed_has_reason"),
        CheckConstraint("status <> 'ready' OR (processed_at IS NOT NULL AND storage_path IS NOT NULL)", name="ready_is_complete"),
        CheckConstraint("page_count IS NULL OR page_count > 0", name="page_count_positive"),
    )


class Section(Base):
    __tablename__ = "section"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document.id", ondelete="CASCADE"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("section.id", ondelete="CASCADE"), index=True)
    level: Mapped[int] = mapped_column(SmallInteger)
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint("document_id", "position", name="uq_section_document_position"),
        CheckConstraint("level BETWEEN 1 AND 6", name="level_range"),
        CheckConstraint("(level = 1) = (parent_id IS NULL)", name="only_topics_have_no_parent"),
        CheckConstraint("position >= 0", name="position_non_negative"),
        CheckConstraint("page_end IS NULL OR page_start IS NULL OR page_end >= page_start", name="page_order"),
    )


class Chunk(CreatedAtMixin, Base):
    __tablename__ = "chunk"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("section.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    page: Mapped[int | None] = mapped_column(Integer)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))

    __table_args__ = (
        UniqueConstraint("section_id", "position", name="uq_chunk_section_position"),
        CheckConstraint("length(content) > 0", name="content_not_empty"),
        CheckConstraint("token_count BETWEEN 1 AND 2000", name="token_count_range"),
        Index("ix_chunk_embedding_hnsw", "embedding", postgresql_using="hnsw",
              postgresql_ops={"embedding": "vector_cosine_ops"}),
        Index("ix_chunk_content_fts", text("to_tsvector('english', content)"), postgresql_using="gin"),
    )
