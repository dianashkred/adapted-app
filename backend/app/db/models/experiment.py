import uuid

from sqlalchemy import CheckConstraint, ForeignKey, SmallInteger, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin
from app.db.enums import TestKind, pg_enum


class TestForm(CreatedAtMixin, Base):
    __test__ = False
    __tablename__ = "test_form"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("course.id", ondelete="CASCADE"))
    kind: Mapped[TestKind] = mapped_column(pg_enum(TestKind, "test_kind"))
    title: Mapped[str] = mapped_column(String(200))

    __table_args__ = (UniqueConstraint("course_id", "kind", name="uq_test_form_course_kind"),)


class TestFormItem(Base):
    __test__ = False
    __tablename__ = "test_form_item"

    form_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("test_form.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("question.id", ondelete="NO ACTION"), index=True)

    __table_args__ = (
        UniqueConstraint("form_id", "question_id", name="uq_test_form_item_question"),
        CheckConstraint("position >= 1", name="position_positive"),
    )


class SimulatedGap(Base):
    __tablename__ = "simulated_gap"

    learner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("learner.id", ondelete="CASCADE"), primary_key=True)
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("section.id", ondelete="CASCADE"), primary_key=True, index=True)
