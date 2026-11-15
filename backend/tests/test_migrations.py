"""Schema versioning: migration 0006 can be reverted and re-applied; its downgrade never loses data silently."""

import pytest
from alembic import command
from sqlalchemy import text

from tests.conftest import alembic_cfg


def _revision(engine):
    with engine.connect() as c:
        c.execute(text("SET ROLE admin"))
        return c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def test_downgrade_0006_and_upgrade_again_on_an_empty_database(migrator_engine, app_engine):
    with migrator_engine.connect() as c:
        c.execute(text("SET ROLE admin"))
        assert c.execute(text("SELECT count(*) FROM learner")).scalar_one() == 0      # empty database
    cfg = alembic_cfg()
    try:
        command.downgrade(cfg, "0005")
        assert _revision(migrator_engine) == "0005"
        with migrator_engine.connect() as c:
            c.execute(text("SET ROLE admin"))
            assert c.execute(text("SELECT to_regclass('review_item') IS NULL AND to_regtype('answer_confidence') IS NULL")).scalar_one()
            assert c.execute(text("SELECT enum_range(NULL::quiz_kind)::text")).scalar_one() == "{check,review,pre_test,post_test}"
    finally:
        command.upgrade(cfg, "head")
        app_engine.dispose()                     # pooled sessions may have cached the old quiz_kind type
    assert _revision(migrator_engine) == "0006"


def test_downgrade_refuses_to_drop_simulated_learners(migrator_engine, app_engine):
    with migrator_engine.connect() as c:
        c.execute(text("SET ROLE admin"))
        sim = c.execute(text("INSERT INTO learner (account_id, is_simulated) VALUES (NULL, true) RETURNING id")).scalar_one()
        c.commit()
    try:
        with pytest.raises(Exception, match="simulated learners exist"):
            command.downgrade(alembic_cfg(), "0005")
        assert _revision(migrator_engine) == "0006"          # nothing changed (one transaction)
    finally:
        with migrator_engine.connect() as c:
            c.execute(text("SET ROLE admin"))
            c.execute(text("DELETE FROM learner WHERE id = :l"), dict(l=sim))
            c.commit()
        app_engine.dispose()
