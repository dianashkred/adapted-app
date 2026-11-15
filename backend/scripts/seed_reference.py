"""Fill (or refresh) the reference tables. Run as the migrator (reference data belongs to admin).

    python -m scripts.seed_reference
"""

from pathlib import Path

from sqlalchemy import create_engine, text

from app.core.config import get_settings

SQL_FILE = Path(__file__).resolve().parents[1] / "app" / "db" / "sql" / "reference_data.sql"


def main(url: str | None = None) -> None:
    engine = create_engine(url or get_settings().migrator_database_url)
    with engine.begin() as conn:
        conn.execute(text("SET ROLE admin"))
        conn.exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))
        rules = conn.execute(text("SELECT count(*) FROM adaptation_rule")).scalar_one()
        notices = conn.execute(text("SELECT count(*) FROM privacy_notice")).scalar_one()
    print(f"reference data ok: {notices} privacy notice version(s), {rules} adaptation rules")


if __name__ == "__main__":
    main()
