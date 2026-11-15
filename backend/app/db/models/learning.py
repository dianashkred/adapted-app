"""Learner model (topic status per learner and topic) and the log of adaptation decisions."""

import uuid
from datetime import datetime

from sqlalchemy import (BigInteger, CheckConstraint, DateTime, ForeignKey, Identity, Index, Integer,
                        SmallInteger, String, text)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin
from app.db.enums import DifficultyLevel, ReviewReason, TopicStatus, pg_enum


class TopicState(Base):
    """Status, level and counters of one learner for one topic.

    The counters are a documented denormalisation of ``attempt``: they are maintained by the
    trigger ``trg_attempt_apply`` in the same transaction as the answer.
    """

    __tablename__ = "topic_state"

    learner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("learner.id", ondelete="CASCADE"), primary_key=True)
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("section.id", ondelete="CASCADE"), primary_key=True, index=True)
    status: Mapped[TopicStatus] = mapped_column(pg_enum(TopicStatus, "topic_status"), server_default=TopicStatus.NOT_CHECKED.value)
    current_level: Mapped[DifficultyLevel] = mapped_column(
        pg_enum(DifficultyLevel, "difficulty_level"), server_default=DifficultyLevel.INTERMEDIATE.value)
    attempts_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    correct_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    consecutive_errors: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        CheckConstraint("attempts_count >= 0 AND correct_count >= 0 AND correct_count <= attempts_count",
                        name="counters_consistent"),
        CheckConstraint("consecutive_errors >= 0", name="consecutive_errors_non_negative"),
        Index("ix_topic_state_learner_gaps", "learner_id", postgresql_where=text("status = 'gap'")),
        Index("ix_topic_state_due_reviews", "learner_id", "next_review_at",
              postgresql_where=text("next_review_at IS NOT NULL")),
    )


class AdaptationEvent(CreatedAtMixin, Base):
    """Every decision of the tutor is logged so that it can be explained and analysed (US-12)."""

    __tablename__ = "adaptation_event"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    learner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("learner.id", ondelete="CASCADE"))
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("section.id", ondelete="CASCADE"), index=True)
    attempt_id: Mapped[int | None] = mapped_column(ForeignKey("attempt.id", ondelete="CASCADE"), index=True)
    quiz_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("quiz.id", ondelete="CASCADE"), index=True)
    rule: Mapped[str] = mapped_column(ForeignKey("adaptation_rule.code", ondelete="RESTRICT"), index=True)
    from_level: Mapped[DifficultyLevel | None] = mapped_column(pg_enum(DifficultyLevel, "difficulty_level"))
    to_level: Mapped[DifficultyLevel | None] = mapped_column(pg_enum(DifficultyLevel, "difficulty_level"))

    __table_args__ = (
        Index("ix_adaptation_event_learner_section", "learner_id", "section_id", "created_at"),
    )


class ReviewItem(Base):
    """A question on the learner's review list (decision 0002, rule 3); maintained by trg_attempt_review_list.

    Added when an answer is incorrect or not sure, due one day later, resolved by a later correct answer
    given with confidence ``sure``. The attempt links use SET NULL: they are provenance only.
    """

    __tablename__ = "review_item"

    learner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("learner.id", ondelete="CASCADE"), primary_key=True)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("question.id", ondelete="CASCADE"), primary_key=True, index=True)
    reason: Mapped[ReviewReason] = mapped_column(pg_enum(ReviewReason, "review_reason"))
    first_attempt_id: Mapped[int | None] = mapped_column(ForeignKey("attempt.id", ondelete="SET NULL"), index=True)
    last_attempt_id: Mapped[int | None] = mapped_column(ForeignKey("attempt.id", ondelete="SET NULL"), index=True)
    times_added: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("times_added >= 1", name="times_added_positive"),
        CheckConstraint("due_at >= added_at", name="due_after_added"),
        CheckConstraint("resolved_at IS NULL OR resolved_at >= added_at", name="resolved_after_added"),
        Index("ix_review_item_open_due", "learner_id", "due_at", postgresql_where=text("resolved_at IS NULL")),
    )
