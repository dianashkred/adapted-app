"""Structure, roles and access rights (Database criterion: Design, Deployment, Usage)."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.core.config import get_settings
from tests.conftest import scalar

EXPECTED_TABLES = {
    "privacy_notice", "adaptation_rule", "account", "learner", "course", "document", "section", "chunk",
    "question", "question_option", "quiz", "quiz_item", "attempt", "topic_state", "adaptation_event",
    "chat_session", "message", "message_source", "test_form", "test_form_item",
    "review_item", "simulated_gap",                                   # migration 0006
}


def test_all_tables_exist_and_are_owned_by_admin(migrator_engine):
    with migrator_engine.connect() as c:
        rows = dict(c.execute(text("SELECT tablename, tableowner FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'")).all())
    assert set(rows) == EXPECTED_TABLES
    assert set(rows.values()) == {"admin"}


def test_every_table_has_a_primary_key(conn):
    missing = conn.execute(text("""
        SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname <> 'alembic_version'
           AND NOT EXISTS (SELECT 1 FROM pg_constraint p WHERE p.conrelid = c.oid AND p.contype = 'p')""")).scalars().all()
    assert missing == []


def test_every_foreign_key_is_indexed(conn):
    """Unindexed FKs make cascading deletes (US-03) and joins slow."""
    unindexed = conn.execute(text("""
        SELECT con.conrelid::regclass || '.' || con.conname
          FROM pg_constraint con
         WHERE con.contype = 'f' AND con.connamespace = 'public'::regnamespace
           AND NOT EXISTS (SELECT 1 FROM pg_index i
                            WHERE i.indrelid = con.conrelid
                              AND (i.indkey::int2[])[0:cardinality(con.conkey) - 1] = con.conkey)""")).scalars().all()
    assert unindexed == []


def test_relationship_types_present(conn):
    # 1:1 (account-learner), 1:N (course-document), N:M (quiz-question via quiz_item), self-reference (section)
    assert scalar(conn, "SELECT count(*) FROM pg_constraint WHERE conname = 'uq_learner_account_id'") == 1
    assert scalar(conn, "SELECT count(*) FROM pg_constraint WHERE conname = 'fk_section_parent_id_section'") == 1


def test_app_role_is_not_superuser_and_cannot_change_the_schema(conn):
    assert scalar(conn, "SELECT current_user") == "adapted_app"
    assert scalar(conn, "SELECT rolsuper FROM pg_roles WHERE rolname = current_user") is False
    with pytest.raises(ProgrammingError, match="permission denied"):
        conn.execute(text("CREATE TABLE hack (id int)"))


def test_app_cannot_change_reference_data(conn):
    with pytest.raises(ProgrammingError, match="permission denied"):
        conn.execute(text("INSERT INTO adaptation_rule VALUES ('x', 'y')"))


def test_app_read_cannot_write(conn, make):
    conn.execute(text("SET ROLE app_read"))
    assert scalar(conn, "SELECT count(*) FROM course") >= 0
    with pytest.raises(ProgrammingError, match="permission denied"):
        conn.execute(text("INSERT INTO course (title, visibility) VALUES ('x', 'shared')"))


def test_app_cannot_read_migration_table(conn):
    with pytest.raises(ProgrammingError, match="permission denied"):
        conn.execute(text("SELECT * FROM alembic_version"))


def test_new_tables_get_rights_automatically(migrator_engine, app_engine):
    """Default privileges: a table created later by admin is usable by the app without extra GRANTs."""
    with migrator_engine.connect() as m:
        m.execute(text("SET ROLE admin"))
        m.execute(text("CREATE TABLE tmp_default_priv (id int)"))
        m.commit()
    try:
        with app_engine.connect() as a:
            a.execute(text("INSERT INTO tmp_default_priv VALUES (1)"))
            assert a.execute(text("SELECT count(*) FROM tmp_default_priv")).scalar_one() == 1
            a.rollback()
    finally:
        with migrator_engine.connect() as m:
            m.execute(text("SET ROLE admin"))
            m.execute(text("DROP TABLE tmp_default_priv"))
            m.commit()


def test_analyst_sees_only_pseudonymised_views():
    with create_engine(get_settings().test_analyst_database_url).connect() as c:
        assert c.execute(text("SELECT count(*) FROM analytics.v_attempt")).scalar_one() >= 0
        with pytest.raises(ProgrammingError):
            c.execute(text("SELECT * FROM account"))


def test_views_expose_no_personal_data(conn):
    cols = conn.execute(text("""SELECT table_schema || '.' || table_name || '.' || column_name FROM information_schema.columns
                                 WHERE (table_schema = 'analytics' OR table_name = 'account_masked')
                                   AND column_name ~ 'email_encrypted|auth_subject|^email$'""")).scalars().all()
    assert cols == []


def test_functions_are_not_executable_by_public(conn):
    assert scalar(conn, "SELECT has_function_privilege('public', 'start_check(uuid, uuid)', 'EXECUTE')") is False


@pytest.mark.parametrize("fn", ["quiz_review(uuid)", "revision_offer(uuid, uuid, int)"])
def test_new_functions_are_granted_only_to_the_application(conn, fn):
    assert scalar(conn, f"SELECT has_function_privilege('app_write', '{fn}', 'EXECUTE')") is True
    assert scalar(conn, f"SELECT has_function_privilege('public', '{fn}', 'EXECUTE')") is False
    assert scalar(conn, f"SELECT has_function_privilege('analytics_read', '{fn}', 'EXECUTE')") is False


def test_analyst_reads_new_views_but_not_new_tables():
    with create_engine(get_settings().test_analyst_database_url).connect() as c:
        for view in ("v_confidence_calibration", "v_gap_detection"):
            assert c.execute(text(f"SELECT count(*) FROM analytics.{view}")).scalar_one() >= 0
        for table in ("review_item", "simulated_gap", "learner"):
            with pytest.raises(ProgrammingError):
                with c.begin_nested():
                    c.execute(text(f"SELECT * FROM {table}"))
