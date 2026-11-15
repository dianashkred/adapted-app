"""Chats and guided lessons, their messages and the chunks shown as sources."""

import uuid
from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Identity, Index,
                        Integer, SmallInteger, String, Text, text)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin
from app.db.enums import ChatMode, MessageRole, pg_enum


class ChatSession(Base):
    __tablename__ = "chat_session"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    learner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("learner.id", ondelete="CASCADE"))
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("section.id", ondelete="CASCADE"), index=True)
    mode: Mapped[ChatMode] = mapped_column(pg_enum(ChatMode, "chat_mode"))
    current_step: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    total_steps: Mapped[int | None] = mapped_column(SmallInteger)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("(mode = 'guided') = (total_steps IS NOT NULL)", name="steps_only_for_guided"),
        CheckConstraint("current_step >= 0 AND (total_steps IS NULL OR current_step <= total_steps)", name="step_range"),
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="time_order"),
        Index("ix_chat_session_learner_started", "learner_id", "started_at"),
    )


class Message(CreatedAtMixin, Base):
    __tablename__ = "message"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_session.id", ondelete="CASCADE"))
    role: Mapped[MessageRole] = mapped_column(pg_enum(MessageRole, "message_role"))
    content: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(100))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    max_similarity: Mapped[float | None] = mapped_column(Float)
    is_refusal: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))

    __table_args__ = (
        CheckConstraint("length(content) > 0", name="content_not_empty"),
        CheckConstraint("role = 'assistant' OR length(content) <= 1000", name="question_length"),
        CheckConstraint("role = 'assistant' OR (model IS NULL AND latency_ms IS NULL AND NOT is_refusal)",
                        name="llm_fields_only_for_answers"),
        CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="latency_non_negative"),
        CheckConstraint("max_similarity IS NULL OR max_similarity BETWEEN -1 AND 1", name="similarity_range"),
        Index("ix_message_session_id", "session_id", "id"),
    )


class MessageSource(Base):
    __tablename__ = "message_source"

    message_id: Mapped[int] = mapped_column(ForeignKey("message.id", ondelete="CASCADE"), primary_key=True)
    chunk_id: Mapped[int] = mapped_column(ForeignKey("chunk.id", ondelete="CASCADE"), primary_key=True, index=True)
    rank: Mapped[int] = mapped_column(SmallInteger)
    similarity: Mapped[float] = mapped_column(Float)

    __table_args__ = (
        CheckConstraint("rank BETWEEN 1 AND 20", name="rank_range"),
        CheckConstraint("similarity BETWEEN -1 AND 1", name="similarity_range"),
    )
