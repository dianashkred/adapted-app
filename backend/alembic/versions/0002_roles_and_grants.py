"""Access rights: app_read, app_write, admin, analytics_read; default privileges for new objects.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

REFERENCE_TABLES = "privacy_notice, adaptation_rule"


def upgrade() -> None:
    op.execute("""
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_read') THEN CREATE ROLE app_read NOLOGIN; END IF;
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_write') THEN CREATE ROLE app_write NOLOGIN IN ROLE app_read; END IF;
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'analytics_read') THEN CREATE ROLE analytics_read NOLOGIN; END IF;
    END $$;
    """)

    op.execute("GRANT USAGE ON SCHEMA public TO app_read")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO app_read")
    op.execute("GRANT INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_write")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_write")
    op.execute(f"REVOKE INSERT, UPDATE, DELETE ON {REFERENCE_TABLES} FROM app_write")
    op.execute("REVOKE ALL ON alembic_version FROM app_read, app_write")

    op.execute("ALTER DEFAULT PRIVILEGES FOR ROLE admin IN SCHEMA public GRANT SELECT ON TABLES TO app_read")
    op.execute("ALTER DEFAULT PRIVILEGES FOR ROLE admin IN SCHEMA public GRANT INSERT, UPDATE, DELETE ON TABLES TO app_write")
    op.execute("ALTER DEFAULT PRIVILEGES FOR ROLE admin IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO app_write")
    op.execute("ALTER DEFAULT PRIVILEGES FOR ROLE admin REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC")

    op.execute("CREATE SCHEMA IF NOT EXISTS analytics AUTHORIZATION admin")
    op.execute("REVOKE ALL ON SCHEMA analytics FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA analytics TO analytics_read, app_read")
    op.execute("ALTER DEFAULT PRIVILEGES FOR ROLE admin IN SCHEMA analytics GRANT SELECT ON TABLES TO analytics_read")


def downgrade() -> None:
    op.execute("ALTER DEFAULT PRIVILEGES FOR ROLE admin IN SCHEMA analytics REVOKE SELECT ON TABLES FROM analytics_read")
    op.execute("DROP SCHEMA IF EXISTS analytics CASCADE")
    op.execute("ALTER DEFAULT PRIVILEGES FOR ROLE admin GRANT EXECUTE ON FUNCTIONS TO PUBLIC")
    op.execute("ALTER DEFAULT PRIVILEGES FOR ROLE admin IN SCHEMA public REVOKE USAGE, SELECT ON SEQUENCES FROM app_write")
    op.execute("ALTER DEFAULT PRIVILEGES FOR ROLE admin IN SCHEMA public REVOKE INSERT, UPDATE, DELETE ON TABLES FROM app_write")
    op.execute("ALTER DEFAULT PRIVILEGES FOR ROLE admin IN SCHEMA public REVOKE SELECT ON TABLES FROM app_read")
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM app_write")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM app_read, app_write")
    op.execute("REVOKE USAGE ON SCHEMA public FROM app_read")
