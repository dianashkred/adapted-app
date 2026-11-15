from cryptography.fernet import Fernet
from sqlalchemy import text

from app.core import crypto
from app.core.config import get_settings
from scripts import seed_demo, seed_reference


def test_reference_seed_is_idempotent(migrator_engine):
    s = get_settings()
    seed_reference.main(s.test_migrator_database_url)
    seed_reference.main(s.test_migrator_database_url)
    with migrator_engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM adaptation_rule")).scalar_one() == 6


def test_demo_seed_runs_and_covers_edge_cases(app_engine, migrator_engine):
    s = get_settings()
    seed_demo.main(s.test_database_url)
    seed_demo.main(s.test_database_url)
    try:
        with app_engine.connect() as c:
            reasons = set(c.execute(text("SELECT end_reason::text FROM quiz WHERE kind = 'check' AND end_reason IS NOT NULL")).scalars())
            assert reasons == {"success_sequence", "two_consecutive_errors", "question_limit", "stopped_by_learner"}
            statuses = set(c.execute(text("SELECT status::text FROM document")).scalars())
            assert statuses == {"ready", "processing", "failed"}
            assert c.execute(text("SELECT count(*) FROM account")).scalar_one() == 6
            assert set(c.execute(text("SELECT DISTINCT confidence::text FROM attempt WHERE confidence IS NOT NULL")).scalars()) \
                == {"sure", "not_sure", "guessing"}
            assert c.execute(text("SELECT count(*) FILTER (WHERE resolved_at IS NULL) > 0 AND count(*) FILTER (WHERE resolved_at IS NOT NULL) > 0 "
                                  "FROM review_item")).scalar_one()
            assert set(c.execute(text("SELECT reason::text FROM review_item")).scalars()) == {"incorrect", "unsure"}
            assert set(c.execute(text("SELECT kind::text FROM quiz WHERE kind IN ('topic_quiz', 'revision') AND status = 'completed'")).scalars()) \
                == {"topic_quiz", "revision"}
            assert c.execute(text("SELECT count(*) FROM learner WHERE ui_theme = 'dark' AND NOT revision_reminders")).scalar_one() == 1
            assert c.execute(text("SELECT count(*) FROM learner WHERE is_simulated AND account_id IS NULL")).scalar_one() == 3
            assert c.execute(text("""SELECT count(*) FROM review_item r JOIN learner l ON l.id = r.learner_id
                                      WHERE l.experiment_mode = 'plain_rag'""")).scalar_one() == 0
        with migrator_engine.connect() as m:
            m.execute(text("SET ROLE admin"))
            result = dict(m.execute(text("SELECT result, count(*) FROM analytics.v_gap_detection GROUP BY result")).all())
            assert result == {"TP": 1, "FP": 1, "FN": 1, "TN": 9}
            m.execute(text("SELECT analytics.refresh_summaries()"))
            real_checks = m.execute(text("SELECT count(*) FROM analytics.v_check_session WHERE status = 'completed' AND NOT is_simulated")).scalar_one()
            assert m.execute(text("SELECT sum(checks) FROM analytics.mv_check_summary")).scalar_one() == real_checks
            assert m.execute(text("SELECT count(*) FROM analytics.v_check_session WHERE is_simulated")).scalar_one() == 4
            m.commit()
    finally:
        with app_engine.connect() as c:
            c.execute(text("DELETE FROM course WHERE owner_account_id IS NULL"))
            c.execute(text("DELETE FROM account"))
            c.execute(text("DELETE FROM learner WHERE is_simulated"))
            c.commit()


def test_email_encryption_round_trip():
    key = Fernet.generate_key().decode()
    token = crypto.encrypt_email(" Diana@Example.com ", key)
    assert b"diana" not in token
    assert crypto.decrypt_email(token, key) == "diana@example.com"


def test_email_hash_is_stable_and_normalised():
    assert crypto.email_hash("A@B.com", "p") == crypto.email_hash(" a@b.com", "p")
    assert len(crypto.email_hash("a@b.com", "p")) == 64


def test_mask_email():
    assert crypto.mask_email("diana@example.com") == "d***@example.com"
