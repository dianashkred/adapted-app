"""Accounts (the only table with personal data) and pseudonymous learners."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, LargeBinary, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin
from app.db.enums import AccountRole, DifficultyLevel, ExperimentMode, UiTheme, pg_enum


class Account(CreatedAtMixin, Base):
    __tablename__ = "account"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    auth_subject: Mapped[str] = mapped_column(String(64), unique=True)
    email_hash: Mapped[str] = mapped_column(String(64), unique=True)
    email_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    role: Mapped[AccountRole] = mapped_column(pg_enum(AccountRole, "account_role"), server_default=AccountRole.STUDENT.value)
    consent_version: Mapped[str] = mapped_column(ForeignKey("privacy_notice.version", ondelete="RESTRICT"), index=True)
    consent_given_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("email_hash ~ '^[0-9a-f]{64}$'", name="email_hash_hex"),
        CheckConstraint("consent_given_at <= now() + interval '1 minute'", name="consent_not_in_future"),
    )


class Learner(CreatedAtMixin, Base):
    """Pseudonymous identity used by ALL learning data and exports (1:1 with account).

    A simulated learner (US-18, KPI K2) has no account; its ground-truth gaps are in ``simulated_gap``.
    """

    __tablename__ = "learner"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("account.id", ondelete="CASCADE"), unique=True)
    is_participant: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    experiment_mode: Mapped[ExperimentMode | None] = mapped_column(pg_enum(ExperimentMode, "experiment_mode"))
    mode_assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    starting_level: Mapped[DifficultyLevel] = mapped_column(
        pg_enum(DifficultyLevel, "difficulty_level"), server_default=DifficultyLevel.INTERMEDIATE.value
    )
    is_simulated: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    ui_theme: Mapped[UiTheme] = mapped_column(pg_enum(UiTheme, "ui_theme"), server_default=UiTheme.SYSTEM.value)
    revision_reminders: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("experiment_mode IS NULL OR is_participant", name="mode_only_for_participants"),
        CheckConstraint("(experiment_mode IS NULL) = (mode_assigned_at IS NULL)", name="mode_and_time_together"),
        # A real learner has an account; a simulated one has none (decision 0002, rule 9).
        CheckConstraint("(account_id IS NOT NULL) = (NOT is_simulated)", name="account_iff_real"),
    )
