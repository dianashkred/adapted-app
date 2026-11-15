import uuid
from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint,
                        Identity, Index, SmallInteger, Text, UniqueConstraint, text)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin
from app.db.enums import (AnswerConfidence, CheckEndReason, DifficultyLevel, EvaluationMethod, QuestionKind,
                          QuestionSource, QuizKind, QuizStatus, TopicStatus, pg_enum)


class Question(CreatedAtMixin, Base):
    __tablename__ = "question"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("section.id", ondelete="CASCADE"))
    level: Mapped[DifficultyLevel] = mapped_column(pg_enum(DifficultyLevel, "difficulty_level"))
    kind: Mapped[QuestionKind] = mapped_column(pg_enum(QuestionKind, "question_kind"))
    source: Mapped[QuestionSource] = mapped_column(pg_enum(QuestionSource, "question_source"))
    prompt: Mapped[str] = mapped_column(Text)
    reference_answer: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("length(btrim(prompt)) > 0", name="prompt_not_blank"),
        CheckConstraint("length(btrim(reference_answer)) > 0", name="reference_not_blank"),
        Index("ix_question_section_level", "section_id", "level"),
    )


class QuestionOption(Base):
    __tablename__ = "question_option"

    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("question.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    option_text: Mapped[str] = mapped_column(Text)
    is_correct: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))

    __table_args__ = (
        CheckConstraint("position BETWEEN 1 AND 6", name="position_range"),
        CheckConstraint("length(btrim(option_text)) > 0", name="text_not_blank"),
        Index("uq_question_option_one_correct", "question_id", unique=True, postgresql_where=text("is_correct")),
    )


class Quiz(Base):
    __tablename__ = "quiz"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    learner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("learner.id", ondelete="CASCADE"))
    section_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("section.id", ondelete="CASCADE"), index=True)
    kind: Mapped[QuizKind] = mapped_column(pg_enum(QuizKind, "quiz_kind"))
    status: Mapped[QuizStatus] = mapped_column(pg_enum(QuizStatus, "quiz_status"), server_default=QuizStatus.IN_PROGRESS.value)
    max_questions: Mapped[int] = mapped_column(SmallInteger, server_default=text("6"))
    outcome: Mapped[TopicStatus | None] = mapped_column(pg_enum(TopicStatus, "topic_status"))
    end_reason: Mapped[CheckEndReason | None] = mapped_column(pg_enum(CheckEndReason, "check_end_reason"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("max_questions BETWEEN 1 AND 30", name="max_questions_range"),
        CheckConstraint("kind <> 'check' OR (section_id IS NOT NULL AND max_questions <= 6)", name="check_is_per_topic"),
        CheckConstraint("(status = 'in_progress') = (ended_at IS NULL)", name="ended_iff_closed"),
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="time_order"),
        CheckConstraint("kind <> 'check' OR status <> 'completed' OR (outcome IS NOT NULL AND end_reason IS NOT NULL)",
                        name="completed_check_has_result"),
        CheckConstraint("kind = 'check' OR end_reason IS NULL", name="end_reason_only_for_checks"),
        CheckConstraint("kind <> 'topic_quiz' OR section_id IS NOT NULL", name="topic_quiz_is_per_topic"),
        CheckConstraint("kind <> 'revision' OR max_questions BETWEEN 10 AND 20", name="revision_size"),
        Index("uq_quiz_one_open_check", "learner_id", "section_id", unique=True,
              postgresql_where=text("kind = 'check' AND status = 'in_progress'")),
        Index("ix_quiz_learner_started", "learner_id", "started_at"),
    )


class QuizItem(Base):
    __tablename__ = "quiz_item"

    quiz_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quiz.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("question.id", ondelete="CASCADE"), index=True)

    __table_args__ = (
        UniqueConstraint("quiz_id", "question_id", name="uq_quiz_item_question"),
        CheckConstraint("position >= 1", name="position_positive"),
    )


class Attempt(CreatedAtMixin, Base):
    __tablename__ = "attempt"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    learner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("learner.id", ondelete="CASCADE"))
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("question.id", ondelete="CASCADE"))
    quiz_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("quiz.id", ondelete="CASCADE"), index=True)
    level: Mapped[DifficultyLevel] = mapped_column(pg_enum(DifficultyLevel, "difficulty_level"))
    selected_option: Mapped[int | None] = mapped_column(SmallInteger)
    answer_text: Mapped[str | None] = mapped_column(Text)
    is_correct: Mapped[bool] = mapped_column(Boolean)
    evaluated_by: Mapped[EvaluationMethod] = mapped_column(pg_enum(EvaluationMethod, "evaluation_method"))
    feedback: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[AnswerConfidence | None] = mapped_column(pg_enum(AnswerConfidence, "answer_confidence"))

    __table_args__ = (
        ForeignKeyConstraint(["question_id", "selected_option"],
                             ["question_option.question_id", "question_option.position"],
                             name="fk_attempt_selected_option", ondelete="CASCADE"),
        CheckConstraint("num_nonnulls(selected_option, answer_text) = 1", name="one_answer_form"),
        CheckConstraint("answer_text IS NULL OR length(answer_text) <= 4000", name="answer_length"),
        CheckConstraint("(selected_option IS NULL) = (evaluated_by = 'llm')", name="evaluation_matches_form"),
        Index("ix_attempt_learner_created", "learner_id", "created_at"),
        Index("ix_attempt_question_option", "question_id", "selected_option"),
        Index("uq_attempt_quiz_question", "quiz_id", "question_id", unique=True,
              postgresql_where=text("quiz_id IS NOT NULL")),
    )
