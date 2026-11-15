"""Confidence, review list, topic and revision quizzes, learner preferences, simulated profiles.

Revision ID: 0006
Revises: 0005
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


DROP_ANALYTICS_VIEWS = r"""
DROP MATERIALIZED VIEW IF EXISTS analytics.mv_check_summary;
DROP VIEW IF EXISTS analytics.v_gap_detection, analytics.v_confidence_calibration,
                    analytics.v_test_result, analytics.v_answer_quality, analytics.v_check_session,
                    analytics.v_topic_state, analytics.v_attempt;
"""

QUIZ_KIND_DEPENDENTS_DROP = r"""
ALTER TABLE quiz DROP CONSTRAINT IF EXISTS ck_quiz_check_is_per_topic,
                 DROP CONSTRAINT IF EXISTS ck_quiz_completed_check_has_result,
                 DROP CONSTRAINT IF EXISTS ck_quiz_end_reason_only_for_checks,
                 DROP CONSTRAINT IF EXISTS ck_quiz_topic_quiz_is_per_topic,
                 DROP CONSTRAINT IF EXISTS ck_quiz_revision_size;
DROP INDEX IF EXISTS uq_quiz_one_open_check;
"""

QUIZ_KIND_DEPENDENTS_CREATE = r"""
ALTER TABLE quiz
  ADD CONSTRAINT ck_quiz_check_is_per_topic CHECK (kind <> 'check' OR (section_id IS NOT NULL AND max_questions <= 6)),
  ADD CONSTRAINT ck_quiz_completed_check_has_result
      CHECK (kind <> 'check' OR status <> 'completed' OR (outcome IS NOT NULL AND end_reason IS NOT NULL)),
  ADD CONSTRAINT ck_quiz_end_reason_only_for_checks CHECK (kind = 'check' OR end_reason IS NULL);
CREATE UNIQUE INDEX uq_quiz_one_open_check ON quiz (learner_id, section_id) WHERE kind = 'check' AND status = 'in_progress';
"""


UPGRADE_SQL = r"""
CREATE TYPE answer_confidence AS ENUM ('sure', 'not_sure', 'guessing');
CREATE TYPE review_reason     AS ENUM ('incorrect', 'unsure');
CREATE TYPE ui_theme          AS ENUM ('system', 'light', 'dark');

""" + DROP_ANALYTICS_VIEWS + QUIZ_KIND_DEPENDENTS_DROP + r"""
ALTER TYPE quiz_kind RENAME TO quiz_kind_0005;
CREATE TYPE quiz_kind AS ENUM ('check', 'review', 'pre_test', 'post_test', 'topic_quiz', 'revision');
ALTER TABLE quiz ALTER COLUMN kind TYPE quiz_kind USING kind::text::quiz_kind;
DROP TYPE quiz_kind_0005;
""" + QUIZ_KIND_DEPENDENTS_CREATE + r"""
ALTER TABLE quiz
  ADD CONSTRAINT ck_quiz_topic_quiz_is_per_topic CHECK (kind <> 'topic_quiz' OR section_id IS NOT NULL),
  ADD CONSTRAINT ck_quiz_revision_size CHECK (kind <> 'revision' OR max_questions BETWEEN 10 AND 20);

ALTER TABLE learner
  ADD COLUMN is_simulated       boolean     NOT NULL DEFAULT false,
  ADD COLUMN ui_theme           ui_theme    NOT NULL DEFAULT 'system',
  ADD COLUMN revision_reminders boolean     NOT NULL DEFAULT true,
  ADD COLUMN last_seen_at       timestamptz NULL,
  ALTER COLUMN account_id DROP NOT NULL,
  ADD CONSTRAINT ck_learner_account_iff_real CHECK ((account_id IS NOT NULL) = (NOT is_simulated));

ALTER TABLE attempt ADD COLUMN confidence answer_confidence NULL;

CREATE TABLE review_item (
  learner_id       uuid          NOT NULL,
  question_id      uuid          NOT NULL,
  reason           review_reason NOT NULL,
  first_attempt_id bigint        NULL,
  last_attempt_id  bigint        NULL,
  times_added      smallint      NOT NULL DEFAULT 1,
  added_at         timestamptz   NOT NULL DEFAULT now(),
  due_at           timestamptz   NOT NULL,
  resolved_at      timestamptz   NULL,
  CONSTRAINT pk_review_item PRIMARY KEY (learner_id, question_id),
  CONSTRAINT fk_review_item_learner_id_learner FOREIGN KEY (learner_id) REFERENCES learner (id) ON DELETE CASCADE,
  CONSTRAINT fk_review_item_question_id_question FOREIGN KEY (question_id) REFERENCES question (id) ON DELETE CASCADE,
  CONSTRAINT fk_review_item_first_attempt_id_attempt FOREIGN KEY (first_attempt_id) REFERENCES attempt (id) ON DELETE SET NULL,
  CONSTRAINT fk_review_item_last_attempt_id_attempt FOREIGN KEY (last_attempt_id) REFERENCES attempt (id) ON DELETE SET NULL,
  CONSTRAINT ck_review_item_times_added_positive CHECK (times_added >= 1),
  CONSTRAINT ck_review_item_due_after_added CHECK (due_at >= added_at),
  CONSTRAINT ck_review_item_resolved_after_added CHECK (resolved_at IS NULL OR resolved_at >= added_at)
);
CREATE INDEX ix_review_item_question_id ON review_item (question_id);
CREATE INDEX ix_review_item_first_attempt_id ON review_item (first_attempt_id);
CREATE INDEX ix_review_item_last_attempt_id ON review_item (last_attempt_id);
CREATE INDEX ix_review_item_open_due ON review_item (learner_id, due_at) WHERE resolved_at IS NULL;

CREATE TABLE simulated_gap (
  learner_id uuid NOT NULL,
  section_id uuid NOT NULL,
  CONSTRAINT pk_simulated_gap PRIMARY KEY (learner_id, section_id),
  CONSTRAINT fk_simulated_gap_learner_id_learner FOREIGN KEY (learner_id) REFERENCES learner (id) ON DELETE CASCADE,
  CONSTRAINT fk_simulated_gap_section_id_section FOREIGN KEY (section_id) REFERENCES section (id) ON DELETE CASCADE
);
CREATE INDEX ix_simulated_gap_section_id ON simulated_gap (section_id);

CREATE FUNCTION trg_simulated_gap_validate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM learner WHERE id = NEW.learner_id AND is_simulated) THEN
    RAISE EXCEPTION 'ground-truth gaps can be stored only for simulated learners' USING ERRCODE = 'check_violation';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM section WHERE id = NEW.section_id AND level = 1) THEN
    RAISE EXCEPTION 'section % is not a topic (level-1 section)', NEW.section_id USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_simulated_gap_validate BEFORE INSERT OR UPDATE ON simulated_gap
  FOR EACH ROW EXECUTE FUNCTION trg_simulated_gap_validate();

CREATE FUNCTION trg_quiz_adaptive_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.kind IN ('topic_quiz', 'revision')
     AND EXISTS (SELECT 1 FROM learner WHERE id = NEW.learner_id AND experiment_mode = 'plain_rag') THEN
    RAISE EXCEPTION '% is an adaptive feature and is not available in experiment mode A', NEW.kind
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_quiz_adaptive_only BEFORE INSERT OR UPDATE OF kind, learner_id ON quiz
  FOR EACH ROW EXECUTE FUNCTION trg_quiz_adaptive_only();

CREATE OR REPLACE FUNCTION trg_attempt_validate() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  q quiz%ROWTYPE;
  v_answered int;
BEGIN
  IF NEW.quiz_id IS NULL THEN
    RETURN NEW;
  END IF;
  SELECT * INTO q FROM quiz WHERE id = NEW.quiz_id FOR UPDATE;
  IF q.learner_id <> NEW.learner_id THEN
    RAISE EXCEPTION 'attempt and quiz belong to different learners' USING ERRCODE = 'check_violation';
  END IF;
  IF q.status <> 'in_progress' THEN
    RAISE EXCEPTION 'quiz % is already closed', q.id USING ERRCODE = 'check_violation';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM quiz_item WHERE quiz_id = q.id AND question_id = NEW.question_id) THEN
    RAISE EXCEPTION 'question % is not part of quiz %', NEW.question_id, q.id USING ERRCODE = 'check_violation';
  END IF;
  SELECT count(*) INTO v_answered FROM attempt WHERE quiz_id = q.id;
  IF v_answered >= q.max_questions THEN
    RAISE EXCEPTION 'quiz % already has % answers (limit)', q.id, q.max_questions USING ERRCODE = 'check_violation';
  END IF;
  IF q.kind IN ('topic_quiz', 'revision')
     AND (SELECT kind FROM question WHERE id = NEW.question_id) <> 'multiple_choice' THEN
    RAISE EXCEPTION 'a % accepts only multiple-choice questions', q.kind USING ERRCODE = 'check_violation';
  END IF;
  IF q.kind IN ('pre_test', 'post_test') THEN
    IF NEW.confidence IS NOT NULL THEN
      RAISE EXCEPTION 'confidence is not recorded in pre- and post-tests' USING ERRCODE = 'check_violation';
    END IF;
  ELSIF NEW.confidence IS NULL THEN
    RAISE EXCEPTION 'confidence is required for an answer in a % quiz', q.kind USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION trg_attempt_apply() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  q        quiz%ROWTYPE;
  v_topic  uuid;
  v_mode   experiment_mode;
  v_new    difficulty_level;
  s        record;
BEGIN
  IF NEW.quiz_id IS NOT NULL THEN
    SELECT * INTO q FROM quiz WHERE id = NEW.quiz_id;
    IF q.kind IN ('pre_test', 'post_test') THEN
      RETURN NULL;
    END IF;
    IF q.kind IN ('topic_quiz', 'revision') THEN
      IF (SELECT count(*) FROM attempt WHERE quiz_id = q.id) >= q.max_questions THEN
        UPDATE quiz SET status = 'completed', ended_at = now() WHERE id = q.id;
      END IF;
      RETURN NULL;
    END IF;
  END IF;

  v_topic := topic_of((SELECT section_id FROM question WHERE id = NEW.question_id));
  SELECT experiment_mode INTO v_mode FROM learner WHERE id = NEW.learner_id;

  INSERT INTO topic_state AS t (learner_id, section_id, attempts_count, correct_count, consecutive_errors, last_attempt_at)
  VALUES (NEW.learner_id, v_topic, 1, NEW.is_correct::int, (NOT NEW.is_correct)::int, NEW.created_at)
  ON CONFLICT (learner_id, section_id) DO UPDATE
     SET attempts_count     = t.attempts_count + 1,
         correct_count      = t.correct_count + NEW.is_correct::int,
         consecutive_errors = CASE WHEN NEW.is_correct THEN 0 ELSE t.consecutive_errors + 1 END,
         last_attempt_at    = NEW.created_at;

  IF NEW.quiz_id IS NULL OR q.kind <> 'check' THEN
    RETURN NULL;
  END IF;

  s := check_summary(NEW.quiz_id);

  IF v_mode IS DISTINCT FROM 'plain_rag' THEN
    v_new := next_level(NEW.level, NEW.is_correct);
    IF v_new <> NEW.level THEN
      UPDATE topic_state SET current_level = v_new WHERE learner_id = NEW.learner_id AND section_id = v_topic;
      INSERT INTO adaptation_event (learner_id, section_id, attempt_id, quiz_id, rule, from_level, to_level)
      VALUES (NEW.learner_id, v_topic, NEW.id, NEW.quiz_id,
              CASE WHEN NEW.is_correct THEN 'level_up' ELSE 'level_down' END, NEW.level, v_new);
    END IF;

    IF s.last_two_wrong THEN
      INSERT INTO adaptation_event (learner_id, section_id, attempt_id, quiz_id, rule, from_level, to_level)
      VALUES (NEW.learner_id, v_topic, NEW.id, NEW.quiz_id, 'basic_chapter_link', NEW.level, 'basic');
      PERFORM finish_check(NEW.quiz_id, 'two_consecutive_errors');
      RETURN NULL;
    END IF;
    IF s.last_two_correct_advanced THEN
      PERFORM finish_check(NEW.quiz_id, 'success_sequence');
      RETURN NULL;
    END IF;
  END IF;

  IF s.total >= q.max_questions THEN
    PERFORM finish_check(NEW.quiz_id, 'question_limit');
  END IF;
  RETURN NULL;
END $$;

CREATE FUNCTION trg_attempt_review_list() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  v_kind   quiz_kind;
  v_reason review_reason;
BEGIN
  IF NEW.quiz_id IS NULL THEN
    RETURN NULL;
  END IF;
  SELECT kind INTO v_kind FROM quiz WHERE id = NEW.quiz_id;
  IF v_kind NOT IN ('check', 'review', 'topic_quiz', 'revision') THEN
    RETURN NULL;
  END IF;
  IF EXISTS (SELECT 1 FROM learner WHERE id = NEW.learner_id AND experiment_mode = 'plain_rag') THEN
    RETURN NULL;
  END IF;

  v_reason := CASE WHEN NOT NEW.is_correct                      THEN 'incorrect'::review_reason
                   WHEN NEW.confidence IN ('not_sure', 'guessing') THEN 'unsure'::review_reason
              END;
  IF v_reason IS NOT NULL THEN
    INSERT INTO review_item AS r (learner_id, question_id, reason, first_attempt_id, last_attempt_id, added_at, due_at)
    VALUES (NEW.learner_id, NEW.question_id, v_reason, NEW.id, NEW.id, NEW.created_at, NEW.created_at + interval '1 day')
    ON CONFLICT (learner_id, question_id) DO UPDATE
       SET reason          = EXCLUDED.reason,
           last_attempt_id = EXCLUDED.last_attempt_id,
           times_added     = r.times_added + 1,
           due_at          = EXCLUDED.due_at,
           resolved_at     = NULL;
  ELSIF NEW.confidence = 'sure' THEN
    UPDATE review_item
       SET resolved_at = NEW.created_at, last_attempt_id = NEW.id
     WHERE learner_id = NEW.learner_id AND question_id = NEW.question_id AND resolved_at IS NULL;
  END IF;
  RETURN NULL;
END $$;
CREATE TRIGGER trg_attempt_review_list AFTER INSERT ON attempt
  FOR EACH ROW EXECUTE FUNCTION trg_attempt_review_list();

CREATE FUNCTION quiz_review(p_quiz uuid)
RETURNS TABLE (attempt_id bigint, item_position smallint, question_id uuid, prompt text,
               question_kind question_kind, selected_option smallint, selected_text text,
               answer_text text, is_correct boolean, confidence answer_confidence,
               correct_option smallint, correct_text text, reference_answer text, feedback text)
LANGUAGE sql STABLE AS $$
  SELECT a.id, qi.position, a.question_id, qs.prompt, qs.kind, a.selected_option, so.option_text,
         a.answer_text, a.is_correct, a.confidence, co.position, co.option_text, qs.reference_answer, a.feedback
    FROM attempt a
    JOIN question qs             ON qs.id = a.question_id
    LEFT JOIN quiz_item qi       ON qi.quiz_id = a.quiz_id AND qi.question_id = a.question_id
    LEFT JOIN question_option so ON so.question_id = a.question_id AND so.position = a.selected_option
    LEFT JOIN question_option co ON co.question_id = a.question_id AND co.is_correct
   WHERE a.quiz_id = p_quiz
     AND (NOT a.is_correct OR a.confidence IN ('not_sure', 'guessing'))
   ORDER BY qi.position, a.id
$$;

CREATE FUNCTION revision_offer(p_learner uuid, p_course uuid, p_absence_days int DEFAULT 7,
                               OUT offered boolean, OUT reason text)
LANGUAGE plpgsql STABLE AS $$
DECLARE
  l              learner%ROWTYPE;
  v_any_studied  boolean;
  v_first_open   bigint;
  v_last_result  timestamptz;
BEGIN
  offered := false;
  reason  := NULL;
  IF p_absence_days IS NULL OR p_absence_days < 1 THEN
    RAISE EXCEPTION 'absence_days must be at least 1' USING ERRCODE = 'check_violation';
  END IF;
  SELECT * INTO l FROM learner WHERE id = p_learner;
  IF NOT FOUND OR NOT l.revision_reminders OR l.experiment_mode IS NOT DISTINCT FROM 'plain_rag' THEN
    RETURN;
  END IF;

  WITH topics AS (
    SELECT row_number() OVER (ORDER BY d.uploaded_at, d.id, s.position) AS n,
           coalesce(t.status, 'not_checked') <> 'not_checked'            AS studied
      FROM section s
      JOIN document d ON d.id = s.document_id
      LEFT JOIN topic_state t ON t.learner_id = p_learner AND t.section_id = s.id
     WHERE d.course_id = p_course AND s.level = 1
  )
  SELECT coalesce(bool_or(studied), false), min(n) FILTER (WHERE NOT studied)
    INTO v_any_studied, v_first_open
    FROM topics;

  IF NOT v_any_studied THEN
    RETURN;
  END IF;

  IF l.last_seen_at IS NOT NULL AND l.last_seen_at < now() - make_interval(days => p_absence_days) THEN
    offered := true; reason := 'absence';
    RETURN;
  END IF;

  IF v_first_open IS NULL OR v_first_open = 1 THEN
    RETURN;
  END IF;
  SELECT max(z.ended_at) INTO v_last_result
    FROM quiz z JOIN section s ON s.id = z.section_id JOIN document d ON d.id = s.document_id
   WHERE z.learner_id = p_learner AND z.kind = 'check' AND z.outcome IN ('gap', 'mastered') AND d.course_id = p_course;
  IF EXISTS (SELECT 1
               FROM quiz z
               JOIN quiz_item qi ON qi.quiz_id = z.id
               JOIN question qs  ON qs.id = qi.question_id
               JOIN section s    ON s.id = qs.section_id
               JOIN document d   ON d.id = s.document_id
              WHERE z.learner_id = p_learner AND z.kind = 'revision' AND d.course_id = p_course
                AND z.started_at >= coalesce(v_last_result, '-infinity')) THEN
    RETURN;
  END IF;
  offered := true; reason := 'new_topic';
END $$;

CREATE VIEW analytics.v_attempt AS
SELECT a.id            AS attempt_id,
       a.learner_id,
       l.experiment_mode,
       l.is_simulated,
       q.kind          AS quiz_kind,
       topic_of(qs.section_id) AS topic_id,
       a.level,
       a.is_correct,
       a.confidence,
       a.evaluated_by,
       a.created_at
  FROM attempt a
  JOIN learner l   ON l.id = a.learner_id
  JOIN question qs ON qs.id = a.question_id
  LEFT JOIN quiz q ON q.id = a.quiz_id;

CREATE VIEW analytics.v_topic_state AS
SELECT t.learner_id, l.experiment_mode, l.is_simulated, t.section_id AS topic_id, s.title AS topic_title,
       t.status, t.current_level, t.attempts_count, t.correct_count,
       round(t.correct_count::numeric / NULLIF(t.attempts_count, 0), 3) AS correct_rate,
       t.last_attempt_at
  FROM topic_state t
  JOIN learner l ON l.id = t.learner_id
  JOIN section s ON s.id = t.section_id;

CREATE VIEW analytics.v_check_session AS
SELECT q.id AS quiz_id, q.learner_id, l.experiment_mode, l.is_simulated, q.section_id AS topic_id,
       q.status, q.outcome, q.end_reason, q.started_at, q.ended_at,
       count(a.id)                              AS questions_answered,
       count(a.id) FILTER (WHERE a.is_correct)  AS correct_answers
  FROM quiz q
  JOIN learner l ON l.id = q.learner_id
  LEFT JOIN attempt a ON a.quiz_id = q.id
 WHERE q.kind = 'check'
 GROUP BY q.id, l.experiment_mode, l.is_simulated;

CREATE VIEW analytics.v_answer_quality AS
SELECT m.id AS message_id, cs.learner_id, l.experiment_mode, l.is_simulated, cs.section_id AS topic_id,
       m.model, m.latency_ms, m.prompt_tokens, m.completion_tokens, m.max_similarity, m.is_refusal,
       (SELECT count(*) FROM message_source ms WHERE ms.message_id = m.id) AS sources_count,
       m.created_at
  FROM message m
  JOIN chat_session cs ON cs.id = m.session_id
  JOIN learner l ON l.id = cs.learner_id
 WHERE m.role = 'assistant';

CREATE VIEW analytics.v_test_result AS
SELECT q.learner_id, l.experiment_mode, l.is_simulated, q.kind AS test_kind,
       count(a.id) AS answered, count(a.id) FILTER (WHERE a.is_correct) AS correct, q.ended_at
  FROM quiz q
  JOIN learner l ON l.id = q.learner_id
  LEFT JOIN attempt a ON a.quiz_id = q.id
 WHERE q.kind IN ('pre_test', 'post_test')
 GROUP BY q.id, l.experiment_mode, l.is_simulated;

CREATE VIEW analytics.v_confidence_calibration AS
SELECT coalesce(experiment_mode::text, 'not_participant') AS experiment_mode,
       level,
       confidence,
       count(*)                                  AS answers,
       count(*) FILTER (WHERE is_correct)        AS correct,
       round(avg(is_correct::int), 3)            AS correct_rate
  FROM analytics.v_attempt
 WHERE confidence IS NOT NULL AND NOT is_simulated
 GROUP BY 1, 2, 3;

CREATE VIEW analytics.v_gap_detection AS
WITH courses AS (
  SELECT DISTINCT x.learner_id, d.course_id
    FROM (SELECT learner_id, section_id FROM topic_state
          UNION SELECT learner_id, section_id FROM simulated_gap) x
    JOIN learner l  ON l.id = x.learner_id AND l.is_simulated
    JOIN section s  ON s.id = x.section_id
    JOIN document d ON d.id = s.document_id
)
SELECT c.learner_id,
       l.experiment_mode,
       s.id                                         AS topic_id,
       s.title                                      AS topic_title,
       coalesce(t.status, 'not_checked')            AS predicted_status,
       coalesce(t.status = 'gap', false)            AS predicted_gap,
       g.section_id IS NOT NULL                     AS actual_gap,
       CASE WHEN coalesce(t.status = 'gap', false) AND g.section_id IS NOT NULL THEN 'TP'
            WHEN coalesce(t.status = 'gap', false)                              THEN 'FP'
            WHEN g.section_id IS NOT NULL                                       THEN 'FN'
            ELSE 'TN' END                           AS result
  FROM courses c
  JOIN learner l  ON l.id = c.learner_id
  JOIN document d ON d.course_id = c.course_id
  JOIN section s  ON s.document_id = d.id AND s.level = 1
  LEFT JOIN topic_state t   ON t.learner_id = c.learner_id AND t.section_id = s.id
  LEFT JOIN simulated_gap g ON g.learner_id = c.learner_id AND g.section_id = s.id;

CREATE MATERIALIZED VIEW analytics.mv_check_summary AS
SELECT coalesce(experiment_mode::text, 'not_participant') AS experiment_mode,
       count(*)                                       AS checks,
       count(*) FILTER (WHERE outcome = 'mastered')   AS mastered,
       count(*) FILTER (WHERE outcome = 'gap')        AS gaps,
       round(avg(questions_answered), 2)              AS avg_questions
  FROM analytics.v_check_session
 WHERE status = 'completed' AND NOT is_simulated
 GROUP BY 1;
CREATE UNIQUE INDEX uq_mv_check_summary_mode ON analytics.mv_check_summary (experiment_mode);

GRANT EXECUTE ON FUNCTION quiz_review(uuid), revision_offer(uuid, uuid, int) TO app_write, app_read;
"""


DOWNGRADE_GUARD = r"""
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM quiz WHERE kind::text IN ('topic_quiz', 'revision')) THEN
    RAISE EXCEPTION 'downgrade of 0006 refused: topic/revision quizzes exist (delete them first)';
  END IF;
  IF EXISTS (SELECT 1 FROM learner WHERE is_simulated) THEN
    RAISE EXCEPTION 'downgrade of 0006 refused: simulated learners exist (delete them first)';
  END IF;
END $$;
"""

OLD_ATTEMPT_FUNCTIONS = r"""
CREATE OR REPLACE FUNCTION trg_attempt_validate() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  q quiz%ROWTYPE;
  v_answered int;
BEGIN
  IF NEW.quiz_id IS NULL THEN
    RETURN NEW;
  END IF;
  SELECT * INTO q FROM quiz WHERE id = NEW.quiz_id FOR UPDATE;
  IF q.learner_id <> NEW.learner_id THEN
    RAISE EXCEPTION 'attempt and quiz belong to different learners' USING ERRCODE = 'check_violation';
  END IF;
  IF q.status <> 'in_progress' THEN
    RAISE EXCEPTION 'quiz % is already closed', q.id USING ERRCODE = 'check_violation';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM quiz_item WHERE quiz_id = q.id AND question_id = NEW.question_id) THEN
    RAISE EXCEPTION 'question % is not part of quiz %', NEW.question_id, q.id USING ERRCODE = 'check_violation';
  END IF;
  SELECT count(*) INTO v_answered FROM attempt WHERE quiz_id = q.id;
  IF v_answered >= q.max_questions THEN
    RAISE EXCEPTION 'quiz % already has % answers (limit)', q.id, q.max_questions USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION trg_attempt_apply() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  q        quiz%ROWTYPE;
  v_topic  uuid;
  v_mode   experiment_mode;
  v_new    difficulty_level;
  s        record;
BEGIN
  IF NEW.quiz_id IS NOT NULL THEN
    SELECT * INTO q FROM quiz WHERE id = NEW.quiz_id;
    IF q.kind IN ('pre_test', 'post_test') THEN
      RETURN NULL;
    END IF;
  END IF;

  v_topic := topic_of((SELECT section_id FROM question WHERE id = NEW.question_id));
  SELECT experiment_mode INTO v_mode FROM learner WHERE id = NEW.learner_id;

  INSERT INTO topic_state AS t (learner_id, section_id, attempts_count, correct_count, consecutive_errors, last_attempt_at)
  VALUES (NEW.learner_id, v_topic, 1, NEW.is_correct::int, (NOT NEW.is_correct)::int, NEW.created_at)
  ON CONFLICT (learner_id, section_id) DO UPDATE
     SET attempts_count     = t.attempts_count + 1,
         correct_count      = t.correct_count + NEW.is_correct::int,
         consecutive_errors = CASE WHEN NEW.is_correct THEN 0 ELSE t.consecutive_errors + 1 END,
         last_attempt_at    = NEW.created_at;

  IF NEW.quiz_id IS NULL OR q.kind <> 'check' THEN
    RETURN NULL;
  END IF;

  s := check_summary(NEW.quiz_id);

  IF v_mode IS DISTINCT FROM 'plain_rag' THEN
    v_new := next_level(NEW.level, NEW.is_correct);
    IF v_new <> NEW.level THEN
      UPDATE topic_state SET current_level = v_new WHERE learner_id = NEW.learner_id AND section_id = v_topic;
      INSERT INTO adaptation_event (learner_id, section_id, attempt_id, quiz_id, rule, from_level, to_level)
      VALUES (NEW.learner_id, v_topic, NEW.id, NEW.quiz_id,
              CASE WHEN NEW.is_correct THEN 'level_up' ELSE 'level_down' END, NEW.level, v_new);
    END IF;

    IF s.last_two_wrong THEN
      INSERT INTO adaptation_event (learner_id, section_id, attempt_id, quiz_id, rule, from_level, to_level)
      VALUES (NEW.learner_id, v_topic, NEW.id, NEW.quiz_id, 'basic_chapter_link', NEW.level, 'basic');
      PERFORM finish_check(NEW.quiz_id, 'two_consecutive_errors');
      RETURN NULL;
    END IF;
    IF s.last_two_correct_advanced THEN
      PERFORM finish_check(NEW.quiz_id, 'success_sequence');
      RETURN NULL;
    END IF;
  END IF;

  IF s.total >= q.max_questions THEN
    PERFORM finish_check(NEW.quiz_id, 'question_limit');
  END IF;
  RETURN NULL;
END $$;
"""

VIEWS_0005 = r"""
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

CREATE VIEW analytics.v_answer_quality AS
SELECT m.id AS message_id, cs.learner_id, l.experiment_mode, cs.section_id AS topic_id,
       m.model, m.latency_ms, m.prompt_tokens, m.completion_tokens, m.max_similarity, m.is_refusal,
       (SELECT count(*) FROM message_source ms WHERE ms.message_id = m.id) AS sources_count,
       m.created_at
  FROM message m
  JOIN chat_session cs ON cs.id = m.session_id
  JOIN learner l ON l.id = cs.learner_id
 WHERE m.role = 'assistant';

CREATE VIEW analytics.v_test_result AS
SELECT q.learner_id, l.experiment_mode, q.kind AS test_kind,
       count(a.id) AS answered, count(a.id) FILTER (WHERE a.is_correct) AS correct, q.ended_at
  FROM quiz q
  JOIN learner l ON l.id = q.learner_id
  LEFT JOIN attempt a ON a.quiz_id = q.id
 WHERE q.kind IN ('pre_test', 'post_test')
 GROUP BY q.id, l.experiment_mode;

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
"""

DOWNGRADE_SQL = DOWNGRADE_GUARD + DROP_ANALYTICS_VIEWS + r"""
DROP FUNCTION IF EXISTS quiz_review(uuid), revision_offer(uuid, uuid, int);

DROP TRIGGER IF EXISTS trg_attempt_review_list ON attempt;
DROP FUNCTION IF EXISTS trg_attempt_review_list();
DROP TRIGGER IF EXISTS trg_quiz_adaptive_only ON quiz;
DROP FUNCTION IF EXISTS trg_quiz_adaptive_only();
""" + OLD_ATTEMPT_FUNCTIONS + r"""
DROP TABLE IF EXISTS simulated_gap;
DROP FUNCTION IF EXISTS trg_simulated_gap_validate();
DROP TABLE IF EXISTS review_item;

ALTER TABLE attempt DROP COLUMN IF EXISTS confidence;

ALTER TABLE learner
  DROP CONSTRAINT IF EXISTS ck_learner_account_iff_real,
  ALTER COLUMN account_id SET NOT NULL,
  DROP COLUMN IF EXISTS last_seen_at,
  DROP COLUMN IF EXISTS revision_reminders,
  DROP COLUMN IF EXISTS ui_theme,
  DROP COLUMN IF EXISTS is_simulated;
""" + QUIZ_KIND_DEPENDENTS_DROP + r"""
ALTER TYPE quiz_kind RENAME TO quiz_kind_0006;
CREATE TYPE quiz_kind AS ENUM ('check', 'review', 'pre_test', 'post_test');
ALTER TABLE quiz ALTER COLUMN kind TYPE quiz_kind USING kind::text::quiz_kind;
DROP TYPE quiz_kind_0006;
""" + QUIZ_KIND_DEPENDENTS_CREATE + r"""
DROP TYPE IF EXISTS answer_confidence, review_reason, ui_theme;
""" + VIEWS_0005


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
