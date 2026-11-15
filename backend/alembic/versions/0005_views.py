"""Views: pseudonymised analytics (experiment), masked admin view, materialized summary.

Revision ID: 0005
Revises: 0004
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
-- Personal data never appears here: only the pseudonymous learner_id (random UUID).
CREATE VIEW analytics.v_attempt AS
SELECT a.id            AS attempt_id,
       a.learner_id,
       l.experiment_mode,
       q.kind          AS quiz_kind,
       topic_of(qs.section_id) AS topic_id,
       a.level,
       a.is_correct,
       a.evaluated_by,
       a.created_at
  FROM attempt a
  JOIN learner l   ON l.id = a.learner_id
  JOIN question qs ON qs.id = a.question_id
  LEFT JOIN quiz q ON q.id = a.quiz_id;

CREATE VIEW analytics.v_topic_state AS
SELECT t.learner_id, l.experiment_mode, t.section_id AS topic_id, s.title AS topic_title,
       t.status, t.current_level, t.attempts_count, t.correct_count,
       round(t.correct_count::numeric / NULLIF(t.attempts_count, 0), 3) AS correct_rate,
       t.last_attempt_at
  FROM topic_state t
  JOIN learner l ON l.id = t.learner_id
  JOIN section s ON s.id = t.section_id;

CREATE VIEW analytics.v_check_session AS
SELECT q.id AS quiz_id, q.learner_id, l.experiment_mode, q.section_id AS topic_id,
       q.status, q.outcome, q.end_reason, q.started_at, q.ended_at,
       count(a.id)                              AS questions_answered,
       count(a.id) FILTER (WHERE a.is_correct)  AS correct_answers
  FROM quiz q
  JOIN learner l ON l.id = q.learner_id
  LEFT JOIN attempt a ON a.quiz_id = q.id
 WHERE q.kind = 'check'
 GROUP BY q.id, l.experiment_mode;

CREATE VIEW analytics.v_answer_quality AS            -- KPI K1 and NFR-01/02
SELECT m.id AS message_id, cs.learner_id, l.experiment_mode, cs.section_id AS topic_id,
       m.model, m.latency_ms, m.prompt_tokens, m.completion_tokens, m.max_similarity, m.is_refusal,
       (SELECT count(*) FROM message_source ms WHERE ms.message_id = m.id) AS sources_count,
       m.created_at
  FROM message m
  JOIN chat_session cs ON cs.id = m.session_id
  JOIN learner l ON l.id = cs.learner_id
 WHERE m.role = 'assistant';

CREATE VIEW analytics.v_test_result AS               -- KPI K3: pre-test vs post-test
SELECT q.learner_id, l.experiment_mode, q.kind AS test_kind,
       count(a.id) AS answered, count(a.id) FILTER (WHERE a.is_correct) AS correct, q.ended_at
  FROM quiz q
  JOIN learner l ON l.id = q.learner_id
  LEFT JOIN attempt a ON a.quiz_id = q.id
 WHERE q.kind IN ('pre_test', 'post_test')
 GROUP BY q.id, l.experiment_mode;

-- Summary per experiment mode; refreshed by the analyst before an export.
CREATE MATERIALIZED VIEW analytics.mv_check_summary AS
SELECT coalesce(experiment_mode::text, 'not_participant') AS experiment_mode,
       count(*)                                       AS checks,
       count(*) FILTER (WHERE outcome = 'mastered')   AS mastered,
       count(*) FILTER (WHERE outcome = 'gap')        AS gaps,
       round(avg(questions_answered), 2)              AS avg_questions
  FROM analytics.v_check_session
 WHERE status = 'completed'
 GROUP BY 1;
CREATE UNIQUE INDEX uq_mv_check_summary_mode ON analytics.mv_check_summary (experiment_mode);

CREATE FUNCTION analytics.refresh_summaries() RETURNS void LANGUAGE sql SECURITY DEFINER
SET search_path = analytics, public AS $$
  REFRESH MATERIALIZED VIEW CONCURRENTLY analytics.mv_check_summary;
$$;
GRANT EXECUTE ON FUNCTION analytics.refresh_summaries() TO analytics_read;

-- Admin screen: accounts without readable personal data (e-mail stays encrypted; hash shortened).
CREATE VIEW account_masked AS
SELECT a.id AS account_id, l.id AS learner_id, a.role,
       left(a.email_hash, 8) || '…' AS email_hash_short,
       a.consent_version, a.consent_given_at, a.last_login_at, a.created_at,
       l.is_participant, l.experiment_mode
  FROM account a
  LEFT JOIN learner l ON l.account_id = a.id;
"""

DOWNGRADE_SQL = r"""
DROP VIEW IF EXISTS account_masked;
DROP FUNCTION IF EXISTS analytics.refresh_summaries();
DROP MATERIALIZED VIEW IF EXISTS analytics.mv_check_summary;
DROP VIEW IF EXISTS analytics.v_test_result, analytics.v_answer_quality, analytics.v_check_session,
                    analytics.v_topic_state, analytics.v_attempt;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
