"""Reference data (privacy notice versions, adaptation rules) from app/db/sql/reference_data.sql.

Revision ID: 0004
Revises: 0003
"""
from pathlib import Path

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[2] / "app" / "db" / "sql" / "reference_data.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DELETE FROM adaptation_rule")
    op.execute("DELETE FROM privacy_notice")
