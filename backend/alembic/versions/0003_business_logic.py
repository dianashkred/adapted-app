"""Business logic in the database: learner model, knowledge check, integrity triggers, masking.

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
CREATE FUNCTION topic_status_from_answers(p_total int, p_correct int, p_last_two_correct_high boolean)
RETURNS topic_status LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE
           WHEN p_total < 2 THEN 'not_checked'::topic_status
           WHEN p_correct::numeric / p_total >= 0.75 OR p_last_two_correct_high THEN 'mastered'::topic_status
           ELSE 'gap'::topic_status
         END
$$;

CREATE FUNCTION next_level(p_level difficulty_level, p_correct boolean)
RETURNS difficulty_level LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE
           WHEN p_correct AND p_level = 'basic'        THEN 'intermediate'::difficulty_level
           WHEN p_correct                              THEN 'advanced'::difficulty_level
           WHEN NOT p_correct AND p_level = 'advanced' THEN 'intermediate'::difficulty_level
           ELSE 'basic'::difficulty_level
         END
$$;

CREATE FUNCTION topic_of(p_section uuid)
RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  WITH RECURSIVE up AS (
    SELECT id, parent_id FROM section WHERE id = p_section
    UNION ALL
    SELECT s.id, s.parent_id FROM section s JOIN up ON s.id = up.parent_id
  )
  SELECT id FROM up WHERE parent_id IS NULL
$$;

CREATE FUNCTION mask_email(p_email text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE WHEN position('@' IN p_email) > 1
              THEN left(p_email, 1) || '***' || substr(p_email, position('@' IN p_email))
              ELSE '***' END
$$;

CREATE FUNCTION check_summary(p_quiz uuid, OUT total int, OUT correct int, OUT last_two_correct_high boolean,
                              OUT last_two_wrong boolean, OUT last_two_correct_advanced boolean)
LANGUAGE sql STABLE AS $$
  WITH a AS (SELECT is_correct, level, id FROM attempt WHERE quiz_id = p_quiz),
       last2 AS (SELECT is_correct, level FROM a ORDER BY id DESC LIMIT 2)
  SELECT (SELECT count(*)::int FROM a),
         (SELECT count(*) FILTER (WHERE is_correct)::int FROM a),
         (SELECT count(*) = 2 AND bool_and(is_correct AND level IN ('intermediate', 'advanced')) FROM last2),
         (SELECT count(*) = 2 AND bool_and(NOT is_correct) FROM last2),
         (SELECT count(*) = 2 AND bool_and(is_correct AND level = 'advanced') FROM last2)
$$;

CREATE FUNCTION finish_check(p_quiz uuid, p_reason check_end_reason)
RETURNS topic_status LANGUAGE plpgsql AS $$
DECLARE
  q quiz%ROWTYPE;
  s record;
  v_outcome topic_status;
BEGIN
  SELECT * INTO q FROM quiz WHERE id = p_quiz FOR UPDATE;
  s := check_summary(p_quiz);
  v_outcome := topic_status_from_answers(s.total, s.correct, s.last_two_correct_high);

  UPDATE quiz SET status = 'completed', outcome = v_outcome, end_reason = p_reason, ended_at = now()
   WHERE id = p_quiz;

  IF v_outcome <> 'not_checked' THEN
    UPDATE topic_state
       SET status = v_outcome,
           next_review_at = CASE WHEN v_outcome = 'gap' THEN now() + interval '1 day' END
     WHERE learner_id = q.learner_id AND section_id = q.section_id;
    INSERT INTO adaptation_event (learner_id, section_id, quiz_id, rule)
    VALUES (q.learner_id, q.section_id, p_quiz, CASE v_outcome WHEN 'mastered' THEN 'topic_mastered' ELSE 'topic_gap' END);
  END IF;
  RETURN v_outcome;
END $$;

CREATE FUNCTION start_check(p_learner uuid, p_topic uuid)
RETURNS uuid LANGUAGE plpgsql AS $$
DECLARE
  v_quiz uuid;
  v_mode experiment_mode;
BEGIN
  IF topic_of(p_topic) IS DISTINCT FROM p_topic THEN
    RAISE EXCEPTION 'section % is not a topic (level-1 section)', p_topic USING ERRCODE = 'check_violation';
  END IF;

  SELECT id INTO v_quiz FROM quiz
   WHERE learner_id = p_learner AND section_id = p_topic AND kind = 'check' AND status = 'in_progress';
  IF FOUND THEN
    RETURN v_quiz;
  END IF;

  SELECT experiment_mode INTO v_mode FROM learner WHERE id = p_learner;
  INSERT INTO quiz (learner_id, section_id, kind, max_questions)
  VALUES (p_learner, p_topic, 'check', 6) RETURNING id INTO v_quiz;

  INSERT INTO topic_state (learner_id, section_id, current_level)
  VALUES (p_learner, p_topic, 'intermediate')
  ON CONFLICT (learner_id, section_id) DO UPDATE SET current_level = 'intermediate';

  INSERT INTO adaptation_event (learner_id, section_id, quiz_id, rule, to_level)
  VALUES (p_learner, p_topic, v_quiz, 'check_started', 'intermediate');
  RETURN v_quiz;
END $$;

CREATE FUNCTION stop_check(p_quiz uuid)
RETURNS topic_status LANGUAGE plpgsql AS $$
BEGIN
  PERFORM 1 FROM quiz WHERE id = p_quiz AND kind = 'check' AND status = 'in_progress' FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'quiz % is not an open knowledge check', p_quiz USING ERRCODE = 'check_violation';
  END IF;
  RETURN finish_check(p_quiz, 'stopped_by_learner');
END $$;

CREATE FUNCTION trg_attempt_validate() RETURNS trigger LANGUAGE plpgsql AS $$
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

CREATE FUNCTION trg_attempt_apply() RETURNS trigger LANGUAGE plpgsql AS $$
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

CREATE TRIGGER trg_attempt_validate BEFORE INSERT ON attempt
  FOR EACH ROW EXECUTE FUNCTION trg_attempt_validate();
CREATE TRIGGER trg_attempt_apply AFTER INSERT ON attempt
  FOR EACH ROW EXECUTE FUNCTION trg_attempt_apply();

CREATE FUNCTION trg_attempt_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'attempts cannot be changed' USING ERRCODE = 'check_violation';
END $$;
CREATE TRIGGER trg_attempt_immutable BEFORE UPDATE ON attempt
  FOR EACH ROW EXECUTE FUNCTION trg_attempt_immutable();

CREATE FUNCTION assert_question_has_correct(p_question uuid) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM question WHERE id = p_question AND kind = 'multiple_choice')
     AND NOT EXISTS (SELECT 1 FROM question_option WHERE question_id = p_question AND is_correct) THEN
    RAISE EXCEPTION 'multiple-choice question % has no correct option', p_question USING ERRCODE = 'check_violation';
  END IF;
END $$;

CREATE FUNCTION trg_question_has_correct() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  PERFORM assert_question_has_correct(NEW.id);
  RETURN NULL;
END $$;

CREATE FUNCTION trg_option_keeps_correct() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  PERFORM assert_question_has_correct(OLD.question_id);
  RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER trg_question_has_correct AFTER INSERT OR UPDATE ON question
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION trg_question_has_correct();
CREATE CONSTRAINT TRIGGER trg_option_keeps_correct AFTER UPDATE OR DELETE ON question_option
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION trg_option_keeps_correct();

CREATE FUNCTION trg_touch_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END $$;
CREATE TRIGGER trg_topic_state_touch BEFORE UPDATE ON topic_state
  FOR EACH ROW EXECUTE FUNCTION trg_touch_updated_at();

CREATE UNIQUE INDEX uq_attempt_quiz_question ON attempt (quiz_id, question_id) WHERE quiz_id IS NOT NULL;

GRANT EXECUTE ON FUNCTION topic_status_from_answers(int, int, boolean), next_level(difficulty_level, boolean),
                          topic_of(uuid), mask_email(text), check_summary(uuid),
                          start_check(uuid, uuid), stop_check(uuid),
                          finish_check(uuid, check_end_reason), assert_question_has_correct(uuid) TO app_write;
GRANT EXECUTE ON FUNCTION topic_of(uuid), mask_email(text), topic_status_from_answers(int, int, boolean),
                          check_summary(uuid) TO app_read;
GRANT EXECUTE ON FUNCTION topic_of(uuid) TO analytics_read;
"""

DOWNGRADE_SQL = r"""
DROP INDEX IF EXISTS uq_attempt_quiz_question;
DROP TRIGGER IF EXISTS trg_topic_state_touch ON topic_state;
DROP TRIGGER IF EXISTS trg_option_keeps_correct ON question_option;
DROP TRIGGER IF EXISTS trg_question_has_correct ON question;
DROP TRIGGER IF EXISTS trg_attempt_immutable ON attempt;
DROP TRIGGER IF EXISTS trg_attempt_apply ON attempt;
DROP TRIGGER IF EXISTS trg_attempt_validate ON attempt;
DROP FUNCTION IF EXISTS trg_touch_updated_at(), trg_option_keeps_correct(), trg_question_has_correct(), assert_question_has_correct(uuid), trg_attempt_immutable(),
  trg_attempt_apply(), trg_attempt_validate(), stop_check(uuid), start_check(uuid, uuid),
  finish_check(uuid, check_end_reason), check_summary(uuid), mask_email(text), topic_of(uuid),
  next_level(difficulty_level, boolean), topic_status_from_answers(int, int, boolean);
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
