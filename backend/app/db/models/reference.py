from datetime import date

from sqlalchemy import CheckConstraint, Date, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PrivacyNotice(Base):
    __tablename__ = "privacy_notice"

    version: Mapped[str] = mapped_column(String(20), primary_key=True)
    published_on: Mapped[date] = mapped_column(Date)
    summary: Mapped[str] = mapped_column(Text)

    __table_args__ = (CheckConstraint("version ~ '^[0-9]+\\.[0-9]+$'", name="version_format"),)


class AdaptationRule(Base):
    __tablename__ = "adaptation_rule"

    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    description: Mapped[str] = mapped_column(Text)

    __table_args__ = (CheckConstraint("code ~ '^[a-z_]+$'", name="code_format"),)
