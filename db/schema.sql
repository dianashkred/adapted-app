-- AdaptED — DDL of the database (PostgreSQL 16 + pgvector).
-- GENERATED from the Alembic migrations by db/export_schema.sh on 2026-11-15. Do not edit by hand.
-- Prerequisites: roles from db/init/01-roles-and-databases.sh; extension: CREATE EXTENSION vector;

--
-- PostgreSQL database dump
--

\restrict zpZLLtquiEcLH7dcNCvTxJQIKkQ2NB8707Pc1WvueYAsInm4CfzwBPTqW8dCLao

-- Dumped from database version 16.16 (Debian 16.16-1.pgdg12+1)
-- Dumped by pg_dump version 16.16 (Debian 16.16-1.pgdg12+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: analytics; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA analytics;


--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA IF NOT EXISTS public;


--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS 'standard public schema';


--
-- Name: account_role; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.account_role AS ENUM (
    'student',
    'admin'
);


--
-- Name: answer_confidence; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.answer_confidence AS ENUM (
    'sure',
    'not_sure',
    'guessing'
);


--
-- Name: chat_mode; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.chat_mode AS ENUM (
    'guided',
    'free_question'
);


--
-- Name: check_end_reason; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.check_end_reason AS ENUM (
    'success_sequence',
    'two_consecutive_errors',
    'question_limit',
    'stopped_by_learner'
);


--
-- Name: course_visibility; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.course_visibility AS ENUM (
    'private',
    'shared'
);


--
-- Name: difficulty_level; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.difficulty_level AS ENUM (
    'basic',
    'intermediate',
    'advanced'
);


--
-- Name: document_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.document_status AS ENUM (
    'processing',
    'ready',
    'failed'
);


--
-- Name: evaluation_method; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.evaluation_method AS ENUM (
    'auto',
    'llm'
);


--
-- Name: experiment_mode; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.experiment_mode AS ENUM (
    'plain_rag',
    'adaptive'
);


--
-- Name: message_role; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.message_role AS ENUM (
    'user',
    'assistant'
);


--
-- Name: question_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.question_kind AS ENUM (
    'multiple_choice',
    'free_text'
);


--
-- Name: question_source; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.question_source AS ENUM (
    'generated',
    'curated'
);


--
-- Name: quiz_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.quiz_kind AS ENUM (
    'check',
    'review',
    'pre_test',
    'post_test',
    'topic_quiz',
    'revision'
);


--
-- Name: quiz_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.quiz_status AS ENUM (
    'in_progress',
    'completed',
    'abandoned'
);


--
-- Name: review_reason; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.review_reason AS ENUM (
    'incorrect',
    'unsure'
);


--
-- Name: test_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.test_kind AS ENUM (
    'pre_test',
    'post_test'
);


--
-- Name: topic_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.topic_status AS ENUM (
    'not_checked',
    'gap',
    'mastered'
);


--
-- Name: ui_theme; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.ui_theme AS ENUM (
    'system',
    'light',
    'dark'
);


--
-- Name: refresh_summaries(); Type: FUNCTION; Schema: analytics; Owner: -
--

CREATE FUNCTION analytics.refresh_summaries() RETURNS void
    LANGUAGE sql SECURITY DEFINER
    SET search_path TO 'analytics', 'public'
    AS $$
  REFRESH MATERIALIZED VIEW CONCURRENTLY analytics.mv_check_summary;
$$;


--
-- Name: assert_question_has_correct(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.assert_question_has_correct(p_question uuid) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM question WHERE id = p_question AND kind = 'multiple_choice')
     AND NOT EXISTS (SELECT 1 FROM question_option WHERE question_id = p_question AND is_correct) THEN
    RAISE EXCEPTION 'multiple-choice question % has no correct option', p_question USING ERRCODE = 'check_violation';
  END IF;
END $$;


--
-- Name: check_summary(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.check_summary(p_quiz uuid, OUT total integer, OUT correct integer, OUT last_two_correct_high boolean, OUT last_two_wrong boolean, OUT last_two_correct_advanced boolean) RETURNS record
    LANGUAGE sql STABLE
    AS $$
  WITH a AS (SELECT is_correct, level, id FROM attempt WHERE quiz_id = p_quiz),
       last2 AS (SELECT is_correct, level FROM a ORDER BY id DESC LIMIT 2)
  SELECT (SELECT count(*)::int FROM a),
         (SELECT count(*) FILTER (WHERE is_correct)::int FROM a),
         (SELECT count(*) = 2 AND bool_and(is_correct AND level IN ('intermediate', 'advanced')) FROM last2),
         (SELECT count(*) = 2 AND bool_and(NOT is_correct) FROM last2),
         (SELECT count(*) = 2 AND bool_and(is_correct AND level = 'advanced') FROM last2)
$$;


--
-- Name: finish_check(uuid, public.check_end_reason); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.finish_check(p_quiz uuid, p_reason public.check_end_reason) RETURNS public.topic_status
    LANGUAGE plpgsql
    AS $$
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


--
-- Name: mask_email(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.mask_email(p_email text) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    AS $$
  SELECT CASE WHEN position('@' IN p_email) > 1
              THEN left(p_email, 1) || '***' || substr(p_email, position('@' IN p_email))
              ELSE '***' END
$$;


--
-- Name: next_level(public.difficulty_level, boolean); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.next_level(p_level public.difficulty_level, p_correct boolean) RETURNS public.difficulty_level
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    AS $$
  SELECT CASE
           WHEN p_correct AND p_level = 'basic'        THEN 'intermediate'::difficulty_level
           WHEN p_correct                              THEN 'advanced'::difficulty_level
           WHEN NOT p_correct AND p_level = 'advanced' THEN 'intermediate'::difficulty_level
           ELSE 'basic'::difficulty_level
         END
$$;


--
-- Name: quiz_review(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.quiz_review(p_quiz uuid) RETURNS TABLE(attempt_id bigint, item_position smallint, question_id uuid, prompt text, question_kind public.question_kind, selected_option smallint, selected_text text, answer_text text, is_correct boolean, confidence public.answer_confidence, correct_option smallint, correct_text text, reference_answer text, feedback text)
    LANGUAGE sql STABLE
    AS $$
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


--
-- Name: revision_offer(uuid, uuid, integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.revision_offer(p_learner uuid, p_course uuid, p_absence_days integer DEFAULT 7, OUT offered boolean, OUT reason text) RETURNS record
    LANGUAGE plpgsql STABLE
    AS $$
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


--
-- Name: start_check(uuid, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.start_check(p_learner uuid, p_topic uuid) RETURNS uuid
    LANGUAGE plpgsql
    AS $$
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


--
-- Name: stop_check(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.stop_check(p_quiz uuid) RETURNS public.topic_status
    LANGUAGE plpgsql
    AS $$
BEGIN
  PERFORM 1 FROM quiz WHERE id = p_quiz AND kind = 'check' AND status = 'in_progress' FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'quiz % is not an open knowledge check', p_quiz USING ERRCODE = 'check_violation';
  END IF;
  RETURN finish_check(p_quiz, 'stopped_by_learner');
END $$;


--
-- Name: topic_of(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.topic_of(p_section uuid) RETURNS uuid
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
  WITH RECURSIVE up AS (
    SELECT id, parent_id FROM section WHERE id = p_section
    UNION ALL
    SELECT s.id, s.parent_id FROM section s JOIN up ON s.id = up.parent_id
  )
  SELECT id FROM up WHERE parent_id IS NULL
$$;


--
-- Name: topic_status_from_answers(integer, integer, boolean); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.topic_status_from_answers(p_total integer, p_correct integer, p_last_two_correct_high boolean) RETURNS public.topic_status
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    AS $$
  SELECT CASE
           WHEN p_total < 2 THEN 'not_checked'::topic_status
           WHEN p_correct::numeric / p_total >= 0.75 OR p_last_two_correct_high THEN 'mastered'::topic_status
           ELSE 'gap'::topic_status
         END
$$;


--
-- Name: trg_attempt_apply(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.trg_attempt_apply() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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


--
-- Name: trg_attempt_immutable(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.trg_attempt_immutable() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  RAISE EXCEPTION 'attempts cannot be changed' USING ERRCODE = 'check_violation';
END $$;


--
-- Name: trg_attempt_review_list(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.trg_attempt_review_list() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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


--
-- Name: trg_attempt_validate(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.trg_attempt_validate() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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


--
-- Name: trg_option_keeps_correct(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.trg_option_keeps_correct() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  PERFORM assert_question_has_correct(OLD.question_id);
  RETURN NULL;
END $$;


--
-- Name: trg_question_has_correct(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.trg_question_has_correct() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  PERFORM assert_question_has_correct(NEW.id);
  RETURN NULL;
END $$;


--
-- Name: trg_quiz_adaptive_only(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.trg_quiz_adaptive_only() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF NEW.kind IN ('topic_quiz', 'revision')
     AND EXISTS (SELECT 1 FROM learner WHERE id = NEW.learner_id AND experiment_mode = 'plain_rag') THEN
    RAISE EXCEPTION '% is an adaptive feature and is not available in experiment mode A', NEW.kind
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;


--
-- Name: trg_simulated_gap_validate(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.trg_simulated_gap_validate() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM learner WHERE id = NEW.learner_id AND is_simulated) THEN
    RAISE EXCEPTION 'ground-truth gaps can be stored only for simulated learners' USING ERRCODE = 'check_violation';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM section WHERE id = NEW.section_id AND level = 1) THEN
    RAISE EXCEPTION 'section % is not a topic (level-1 section)', NEW.section_id USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;


--
-- Name: trg_touch_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.trg_touch_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END $$;


--
-- Name: v_check_session; Type: VIEW; Schema: analytics; Owner: -
--

CREATE VIEW analytics.v_check_session AS
SELECT
    NULL::uuid AS quiz_id,
    NULL::uuid AS learner_id,
    NULL::public.experiment_mode AS experiment_mode,
    NULL::boolean AS is_simulated,
    NULL::uuid AS topic_id,
    NULL::public.quiz_status AS status,
    NULL::public.topic_status AS outcome,
    NULL::public.check_end_reason AS end_reason,
    NULL::timestamp with time zone AS started_at,
    NULL::timestamp with time zone AS ended_at,
    NULL::bigint AS questions_answered,
    NULL::bigint AS correct_answers;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: mv_check_summary; Type: MATERIALIZED VIEW; Schema: analytics; Owner: -
--

CREATE MATERIALIZED VIEW analytics.mv_check_summary AS
 SELECT COALESCE((experiment_mode)::text, 'not_participant'::text) AS experiment_mode,
    count(*) AS checks,
    count(*) FILTER (WHERE (outcome = 'mastered'::public.topic_status)) AS mastered,
    count(*) FILTER (WHERE (outcome = 'gap'::public.topic_status)) AS gaps,
    round(avg(questions_answered), 2) AS avg_questions
   FROM analytics.v_check_session
  WHERE ((status = 'completed'::public.quiz_status) AND (NOT is_simulated))
  GROUP BY COALESCE((experiment_mode)::text, 'not_participant'::text)
  WITH NO DATA;


--
-- Name: chat_session; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_session (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    learner_id uuid NOT NULL,
    section_id uuid NOT NULL,
    mode public.chat_mode NOT NULL,
    current_step smallint DEFAULT 0 NOT NULL,
    total_steps smallint,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    ended_at timestamp with time zone,
    CONSTRAINT ck_chat_session_step_range CHECK (((current_step >= 0) AND ((total_steps IS NULL) OR (current_step <= total_steps)))),
    CONSTRAINT ck_chat_session_steps_only_for_guided CHECK (((mode = 'guided'::public.chat_mode) = (total_steps IS NOT NULL))),
    CONSTRAINT ck_chat_session_time_order CHECK (((ended_at IS NULL) OR (ended_at >= started_at)))
);


--
-- Name: learner; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.learner (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    account_id uuid,
    is_participant boolean DEFAULT false NOT NULL,
    experiment_mode public.experiment_mode,
    mode_assigned_at timestamp with time zone,
    starting_level public.difficulty_level DEFAULT 'intermediate'::public.difficulty_level NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    is_simulated boolean DEFAULT false NOT NULL,
    ui_theme public.ui_theme DEFAULT 'system'::public.ui_theme NOT NULL,
    revision_reminders boolean DEFAULT true NOT NULL,
    last_seen_at timestamp with time zone,
    CONSTRAINT ck_learner_account_iff_real CHECK (((account_id IS NOT NULL) = (NOT is_simulated))),
    CONSTRAINT ck_learner_mode_and_time_together CHECK (((experiment_mode IS NULL) = (mode_assigned_at IS NULL))),
    CONSTRAINT ck_learner_mode_only_for_participants CHECK (((experiment_mode IS NULL) OR is_participant))
);


--
-- Name: message; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.message (
    id bigint NOT NULL,
    session_id uuid NOT NULL,
    role public.message_role NOT NULL,
    content text NOT NULL,
    model character varying(100),
    latency_ms integer,
    prompt_tokens integer,
    completion_tokens integer,
    max_similarity double precision,
    is_refusal boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_message_content_not_empty CHECK ((length(content) > 0)),
    CONSTRAINT ck_message_latency_non_negative CHECK (((latency_ms IS NULL) OR (latency_ms >= 0))),
    CONSTRAINT ck_message_llm_fields_only_for_answers CHECK (((role = 'assistant'::public.message_role) OR ((model IS NULL) AND (latency_ms IS NULL) AND (NOT is_refusal)))),
    CONSTRAINT ck_message_question_length CHECK (((role = 'assistant'::public.message_role) OR (length(content) <= 1000))),
    CONSTRAINT ck_message_similarity_range CHECK (((max_similarity IS NULL) OR ((max_similarity >= ('-1'::integer)::double precision) AND (max_similarity <= (1)::double precision))))
);


--
-- Name: message_source; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.message_source (
    message_id bigint NOT NULL,
    chunk_id bigint NOT NULL,
    rank smallint NOT NULL,
    similarity double precision NOT NULL,
    CONSTRAINT ck_message_source_rank_range CHECK (((rank >= 1) AND (rank <= 20))),
    CONSTRAINT ck_message_source_similarity_range CHECK (((similarity >= ('-1'::integer)::double precision) AND (similarity <= (1)::double precision)))
);


--
-- Name: v_answer_quality; Type: VIEW; Schema: analytics; Owner: -
--

CREATE VIEW analytics.v_answer_quality AS
 SELECT m.id AS message_id,
    cs.learner_id,
    l.experiment_mode,
    l.is_simulated,
    cs.section_id AS topic_id,
    m.model,
    m.latency_ms,
    m.prompt_tokens,
    m.completion_tokens,
    m.max_similarity,
    m.is_refusal,
    ( SELECT count(*) AS count
           FROM public.message_source ms
          WHERE (ms.message_id = m.id)) AS sources_count,
    m.created_at
   FROM ((public.message m
     JOIN public.chat_session cs ON ((cs.id = m.session_id)))
     JOIN public.learner l ON ((l.id = cs.learner_id)))
  WHERE (m.role = 'assistant'::public.message_role);


--
-- Name: attempt; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.attempt (
    id bigint NOT NULL,
    learner_id uuid NOT NULL,
    question_id uuid NOT NULL,
    quiz_id uuid,
    level public.difficulty_level NOT NULL,
    selected_option smallint,
    answer_text text,
    is_correct boolean NOT NULL,
    evaluated_by public.evaluation_method NOT NULL,
    feedback text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    confidence public.answer_confidence,
    CONSTRAINT ck_attempt_answer_length CHECK (((answer_text IS NULL) OR (length(answer_text) <= 4000))),
    CONSTRAINT ck_attempt_evaluation_matches_form CHECK (((selected_option IS NULL) = (evaluated_by = 'llm'::public.evaluation_method))),
    CONSTRAINT ck_attempt_one_answer_form CHECK ((num_nonnulls(selected_option, answer_text) = 1))
);


--
-- Name: question; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.question (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    section_id uuid NOT NULL,
    level public.difficulty_level NOT NULL,
    kind public.question_kind NOT NULL,
    source public.question_source NOT NULL,
    prompt text NOT NULL,
    reference_answer text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_question_prompt_not_blank CHECK ((length(btrim(prompt)) > 0)),
    CONSTRAINT ck_question_reference_not_blank CHECK ((length(btrim(reference_answer)) > 0))
);


--
-- Name: quiz; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quiz (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    learner_id uuid NOT NULL,
    section_id uuid,
    kind public.quiz_kind NOT NULL,
    status public.quiz_status DEFAULT 'in_progress'::public.quiz_status NOT NULL,
    max_questions smallint DEFAULT 6 NOT NULL,
    outcome public.topic_status,
    end_reason public.check_end_reason,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    ended_at timestamp with time zone,
    CONSTRAINT ck_quiz_check_is_per_topic CHECK (((kind <> 'check'::public.quiz_kind) OR ((section_id IS NOT NULL) AND (max_questions <= 6)))),
    CONSTRAINT ck_quiz_completed_check_has_result CHECK (((kind <> 'check'::public.quiz_kind) OR (status <> 'completed'::public.quiz_status) OR ((outcome IS NOT NULL) AND (end_reason IS NOT NULL)))),
    CONSTRAINT ck_quiz_end_reason_only_for_checks CHECK (((kind = 'check'::public.quiz_kind) OR (end_reason IS NULL))),
    CONSTRAINT ck_quiz_ended_iff_closed CHECK (((status = 'in_progress'::public.quiz_status) = (ended_at IS NULL))),
    CONSTRAINT ck_quiz_max_questions_range CHECK (((max_questions >= 1) AND (max_questions <= 30))),
    CONSTRAINT ck_quiz_revision_size CHECK (((kind <> 'revision'::public.quiz_kind) OR ((max_questions >= 10) AND (max_questions <= 20)))),
    CONSTRAINT ck_quiz_time_order CHECK (((ended_at IS NULL) OR (ended_at >= started_at))),
    CONSTRAINT ck_quiz_topic_quiz_is_per_topic CHECK (((kind <> 'topic_quiz'::public.quiz_kind) OR (section_id IS NOT NULL)))
);


--
-- Name: v_attempt; Type: VIEW; Schema: analytics; Owner: -
--

CREATE VIEW analytics.v_attempt AS
 SELECT a.id AS attempt_id,
    a.learner_id,
    l.experiment_mode,
    l.is_simulated,
    q.kind AS quiz_kind,
    public.topic_of(qs.section_id) AS topic_id,
    a.level,
    a.is_correct,
    a.confidence,
    a.evaluated_by,
    a.created_at
   FROM (((public.attempt a
     JOIN public.learner l ON ((l.id = a.learner_id)))
     JOIN public.question qs ON ((qs.id = a.question_id)))
     LEFT JOIN public.quiz q ON ((q.id = a.quiz_id)));


--
-- Name: v_confidence_calibration; Type: VIEW; Schema: analytics; Owner: -
--

CREATE VIEW analytics.v_confidence_calibration AS
 SELECT COALESCE((experiment_mode)::text, 'not_participant'::text) AS experiment_mode,
    level,
    confidence,
    count(*) AS answers,
    count(*) FILTER (WHERE is_correct) AS correct,
    round(avg((is_correct)::integer), 3) AS correct_rate
   FROM analytics.v_attempt
  WHERE ((confidence IS NOT NULL) AND (NOT is_simulated))
  GROUP BY COALESCE((experiment_mode)::text, 'not_participant'::text), level, confidence;


--
-- Name: document; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.document (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    course_id uuid NOT NULL,
    file_name character varying(255) NOT NULL,
    mime_type character varying(100) NOT NULL,
    size_bytes bigint NOT NULL,
    sha256 character varying(64) NOT NULL,
    storage_path character varying(500),
    status public.document_status DEFAULT 'processing'::public.document_status NOT NULL,
    error_message text,
    page_count integer,
    uploaded_at timestamp with time zone DEFAULT now() NOT NULL,
    processed_at timestamp with time zone,
    CONSTRAINT ck_document_allowed_mime CHECK (((mime_type)::text = ANY ((ARRAY['application/pdf'::character varying, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'::character varying, 'text/plain'::character varying, 'text/markdown'::character varying])::text[]))),
    CONSTRAINT ck_document_failed_has_reason CHECK (((status <> 'failed'::public.document_status) OR (error_message IS NOT NULL))),
    CONSTRAINT ck_document_page_count_positive CHECK (((page_count IS NULL) OR (page_count > 0))),
    CONSTRAINT ck_document_ready_is_complete CHECK (((status <> 'ready'::public.document_status) OR ((processed_at IS NOT NULL) AND (storage_path IS NOT NULL)))),
    CONSTRAINT ck_document_sha256_hex CHECK (((sha256)::text ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT ck_document_size_limit CHECK (((size_bytes > 0) AND (size_bytes <= 52428800)))
);


--
-- Name: section; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.section (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    document_id uuid NOT NULL,
    parent_id uuid,
    level smallint NOT NULL,
    "position" integer NOT NULL,
    title character varying(300) NOT NULL,
    page_start integer,
    page_end integer,
    CONSTRAINT ck_section_level_range CHECK (((level >= 1) AND (level <= 6))),
    CONSTRAINT ck_section_only_topics_have_no_parent CHECK (((level = 1) = (parent_id IS NULL))),
    CONSTRAINT ck_section_page_order CHECK (((page_end IS NULL) OR (page_start IS NULL) OR (page_end >= page_start))),
    CONSTRAINT ck_section_position_non_negative CHECK (("position" >= 0))
);


--
-- Name: simulated_gap; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.simulated_gap (
    learner_id uuid NOT NULL,
    section_id uuid NOT NULL
);


--
-- Name: topic_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.topic_state (
    learner_id uuid NOT NULL,
    section_id uuid NOT NULL,
    status public.topic_status DEFAULT 'not_checked'::public.topic_status NOT NULL,
    current_level public.difficulty_level DEFAULT 'intermediate'::public.difficulty_level NOT NULL,
    attempts_count integer DEFAULT 0 NOT NULL,
    correct_count integer DEFAULT 0 NOT NULL,
    consecutive_errors smallint DEFAULT 0 NOT NULL,
    last_attempt_at timestamp with time zone,
    next_review_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_topic_state_consecutive_errors_non_negative CHECK ((consecutive_errors >= 0)),
    CONSTRAINT ck_topic_state_counters_consistent CHECK (((attempts_count >= 0) AND (correct_count >= 0) AND (correct_count <= attempts_count)))
);


--
-- Name: v_gap_detection; Type: VIEW; Schema: analytics; Owner: -
--

CREATE VIEW analytics.v_gap_detection AS
 WITH courses AS (
         SELECT DISTINCT x.learner_id,
            d_1.course_id
           FROM (((( SELECT topic_state.learner_id,
                    topic_state.section_id
                   FROM public.topic_state
                UNION
                 SELECT simulated_gap.learner_id,
                    simulated_gap.section_id
                   FROM public.simulated_gap) x
             JOIN public.learner l_1 ON (((l_1.id = x.learner_id) AND l_1.is_simulated)))
             JOIN public.section s_1 ON ((s_1.id = x.section_id)))
             JOIN public.document d_1 ON ((d_1.id = s_1.document_id)))
        )
 SELECT c.learner_id,
    l.experiment_mode,
    s.id AS topic_id,
    s.title AS topic_title,
    COALESCE(t.status, 'not_checked'::public.topic_status) AS predicted_status,
    COALESCE((t.status = 'gap'::public.topic_status), false) AS predicted_gap,
    (g.section_id IS NOT NULL) AS actual_gap,
        CASE
            WHEN (COALESCE((t.status = 'gap'::public.topic_status), false) AND (g.section_id IS NOT NULL)) THEN 'TP'::text
            WHEN COALESCE((t.status = 'gap'::public.topic_status), false) THEN 'FP'::text
            WHEN (g.section_id IS NOT NULL) THEN 'FN'::text
            ELSE 'TN'::text
        END AS result
   FROM (((((courses c
     JOIN public.learner l ON ((l.id = c.learner_id)))
     JOIN public.document d ON ((d.course_id = c.course_id)))
     JOIN public.section s ON (((s.document_id = d.id) AND (s.level = 1))))
     LEFT JOIN public.topic_state t ON (((t.learner_id = c.learner_id) AND (t.section_id = s.id))))
     LEFT JOIN public.simulated_gap g ON (((g.learner_id = c.learner_id) AND (g.section_id = s.id))));


--
-- Name: v_test_result; Type: VIEW; Schema: analytics; Owner: -
--

CREATE VIEW analytics.v_test_result AS
SELECT
    NULL::uuid AS learner_id,
    NULL::public.experiment_mode AS experiment_mode,
    NULL::boolean AS is_simulated,
    NULL::public.quiz_kind AS test_kind,
    NULL::bigint AS answered,
    NULL::bigint AS correct,
    NULL::timestamp with time zone AS ended_at;


--
-- Name: v_topic_state; Type: VIEW; Schema: analytics; Owner: -
--

CREATE VIEW analytics.v_topic_state AS
 SELECT t.learner_id,
    l.experiment_mode,
    l.is_simulated,
    t.section_id AS topic_id,
    s.title AS topic_title,
    t.status,
    t.current_level,
    t.attempts_count,
    t.correct_count,
    round(((t.correct_count)::numeric / (NULLIF(t.attempts_count, 0))::numeric), 3) AS correct_rate,
    t.last_attempt_at
   FROM ((public.topic_state t
     JOIN public.learner l ON ((l.id = t.learner_id)))
     JOIN public.section s ON ((s.id = t.section_id)));


--
-- Name: account; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.account (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    auth_subject character varying(64) NOT NULL,
    email_hash character varying(64) NOT NULL,
    email_encrypted bytea NOT NULL,
    role public.account_role DEFAULT 'student'::public.account_role NOT NULL,
    consent_version character varying(20) NOT NULL,
    consent_given_at timestamp with time zone NOT NULL,
    last_login_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_account_consent_not_in_future CHECK ((consent_given_at <= (now() + '00:01:00'::interval))),
    CONSTRAINT ck_account_email_hash_hex CHECK (((email_hash)::text ~ '^[0-9a-f]{64}$'::text))
);


--
-- Name: account_masked; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.account_masked AS
 SELECT a.id AS account_id,
    l.id AS learner_id,
    a.role,
    ("left"((a.email_hash)::text, 8) || '…'::text) AS email_hash_short,
    a.consent_version,
    a.consent_given_at,
    a.last_login_at,
    a.created_at,
    l.is_participant,
    l.experiment_mode
   FROM (public.account a
     LEFT JOIN public.learner l ON ((l.account_id = a.id)));


--
-- Name: adaptation_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.adaptation_event (
    id bigint NOT NULL,
    learner_id uuid NOT NULL,
    section_id uuid NOT NULL,
    attempt_id bigint,
    quiz_id uuid,
    rule character varying(40) NOT NULL,
    from_level public.difficulty_level,
    to_level public.difficulty_level,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: adaptation_event_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.adaptation_event ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.adaptation_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: adaptation_rule; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.adaptation_rule (
    code character varying(40) NOT NULL,
    description text NOT NULL,
    CONSTRAINT ck_adaptation_rule_code_format CHECK (((code)::text ~ '^[a-z_]+$'::text))
);


--
-- Name: attempt_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.attempt ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.attempt_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: chunk; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chunk (
    id bigint NOT NULL,
    section_id uuid NOT NULL,
    "position" integer NOT NULL,
    content text NOT NULL,
    token_count integer NOT NULL,
    page integer,
    embedding public.vector(384) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_chunk_content_not_empty CHECK ((length(content) > 0)),
    CONSTRAINT ck_chunk_token_count_range CHECK (((token_count >= 1) AND (token_count <= 2000)))
);


--
-- Name: chunk_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.chunk ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.chunk_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: course; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.course (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    owner_account_id uuid,
    title character varying(200) NOT NULL,
    language character varying(10) DEFAULT 'en'::character varying NOT NULL,
    visibility public.course_visibility DEFAULT 'private'::public.course_visibility NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_course_private_course_has_owner CHECK (((owner_account_id IS NOT NULL) OR (visibility = 'shared'::public.course_visibility))),
    CONSTRAINT ck_course_title_not_blank CHECK ((length(btrim((title)::text)) > 0))
);


--
-- Name: message_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.message ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.message_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: privacy_notice; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.privacy_notice (
    version character varying(20) NOT NULL,
    published_on date NOT NULL,
    summary text NOT NULL,
    CONSTRAINT ck_privacy_notice_version_format CHECK (((version)::text ~ '^[0-9]+\.[0-9]+$'::text))
);


--
-- Name: question_option; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.question_option (
    question_id uuid NOT NULL,
    "position" smallint NOT NULL,
    option_text text NOT NULL,
    is_correct boolean DEFAULT false NOT NULL,
    CONSTRAINT ck_question_option_position_range CHECK ((("position" >= 1) AND ("position" <= 6))),
    CONSTRAINT ck_question_option_text_not_blank CHECK ((length(btrim(option_text)) > 0))
);


--
-- Name: quiz_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quiz_item (
    quiz_id uuid NOT NULL,
    "position" smallint NOT NULL,
    question_id uuid NOT NULL,
    CONSTRAINT ck_quiz_item_position_positive CHECK (("position" >= 1))
);


--
-- Name: review_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.review_item (
    learner_id uuid NOT NULL,
    question_id uuid NOT NULL,
    reason public.review_reason NOT NULL,
    first_attempt_id bigint,
    last_attempt_id bigint,
    times_added smallint DEFAULT 1 NOT NULL,
    added_at timestamp with time zone DEFAULT now() NOT NULL,
    due_at timestamp with time zone NOT NULL,
    resolved_at timestamp with time zone,
    CONSTRAINT ck_review_item_due_after_added CHECK ((due_at >= added_at)),
    CONSTRAINT ck_review_item_resolved_after_added CHECK (((resolved_at IS NULL) OR (resolved_at >= added_at))),
    CONSTRAINT ck_review_item_times_added_positive CHECK ((times_added >= 1))
);


--
-- Name: test_form; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.test_form (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    course_id uuid NOT NULL,
    kind public.test_kind NOT NULL,
    title character varying(200) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: test_form_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.test_form_item (
    form_id uuid NOT NULL,
    "position" smallint NOT NULL,
    question_id uuid NOT NULL,
    CONSTRAINT ck_test_form_item_position_positive CHECK (("position" >= 1))
);


--
-- Name: account pk_account; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account
    ADD CONSTRAINT pk_account PRIMARY KEY (id);


--
-- Name: adaptation_event pk_adaptation_event; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.adaptation_event
    ADD CONSTRAINT pk_adaptation_event PRIMARY KEY (id);


--
-- Name: adaptation_rule pk_adaptation_rule; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.adaptation_rule
    ADD CONSTRAINT pk_adaptation_rule PRIMARY KEY (code);


--
-- Name: attempt pk_attempt; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attempt
    ADD CONSTRAINT pk_attempt PRIMARY KEY (id);


--
-- Name: chat_session pk_chat_session; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_session
    ADD CONSTRAINT pk_chat_session PRIMARY KEY (id);


--
-- Name: chunk pk_chunk; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chunk
    ADD CONSTRAINT pk_chunk PRIMARY KEY (id);


--
-- Name: course pk_course; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.course
    ADD CONSTRAINT pk_course PRIMARY KEY (id);


--
-- Name: document pk_document; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document
    ADD CONSTRAINT pk_document PRIMARY KEY (id);


--
-- Name: learner pk_learner; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learner
    ADD CONSTRAINT pk_learner PRIMARY KEY (id);


--
-- Name: message pk_message; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message
    ADD CONSTRAINT pk_message PRIMARY KEY (id);


--
-- Name: message_source pk_message_source; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_source
    ADD CONSTRAINT pk_message_source PRIMARY KEY (message_id, chunk_id);


--
-- Name: privacy_notice pk_privacy_notice; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.privacy_notice
    ADD CONSTRAINT pk_privacy_notice PRIMARY KEY (version);


--
-- Name: question pk_question; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question
    ADD CONSTRAINT pk_question PRIMARY KEY (id);


--
-- Name: question_option pk_question_option; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_option
    ADD CONSTRAINT pk_question_option PRIMARY KEY (question_id, "position");


--
-- Name: quiz pk_quiz; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quiz
    ADD CONSTRAINT pk_quiz PRIMARY KEY (id);


--
-- Name: quiz_item pk_quiz_item; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quiz_item
    ADD CONSTRAINT pk_quiz_item PRIMARY KEY (quiz_id, "position");


--
-- Name: review_item pk_review_item; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_item
    ADD CONSTRAINT pk_review_item PRIMARY KEY (learner_id, question_id);


--
-- Name: section pk_section; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.section
    ADD CONSTRAINT pk_section PRIMARY KEY (id);


--
-- Name: simulated_gap pk_simulated_gap; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.simulated_gap
    ADD CONSTRAINT pk_simulated_gap PRIMARY KEY (learner_id, section_id);


--
-- Name: test_form pk_test_form; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.test_form
    ADD CONSTRAINT pk_test_form PRIMARY KEY (id);


--
-- Name: test_form_item pk_test_form_item; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.test_form_item
    ADD CONSTRAINT pk_test_form_item PRIMARY KEY (form_id, "position");


--
-- Name: topic_state pk_topic_state; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.topic_state
    ADD CONSTRAINT pk_topic_state PRIMARY KEY (learner_id, section_id);


--
-- Name: account uq_account_auth_subject; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account
    ADD CONSTRAINT uq_account_auth_subject UNIQUE (auth_subject);


--
-- Name: account uq_account_email_hash; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account
    ADD CONSTRAINT uq_account_email_hash UNIQUE (email_hash);


--
-- Name: chunk uq_chunk_section_position; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chunk
    ADD CONSTRAINT uq_chunk_section_position UNIQUE (section_id, "position");


--
-- Name: document uq_document_course_file; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document
    ADD CONSTRAINT uq_document_course_file UNIQUE (course_id, sha256);


--
-- Name: document uq_document_storage_path; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document
    ADD CONSTRAINT uq_document_storage_path UNIQUE (storage_path);


--
-- Name: learner uq_learner_account_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learner
    ADD CONSTRAINT uq_learner_account_id UNIQUE (account_id);


--
-- Name: quiz_item uq_quiz_item_question; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quiz_item
    ADD CONSTRAINT uq_quiz_item_question UNIQUE (quiz_id, question_id);


--
-- Name: section uq_section_document_position; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.section
    ADD CONSTRAINT uq_section_document_position UNIQUE (document_id, "position");


--
-- Name: test_form uq_test_form_course_kind; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.test_form
    ADD CONSTRAINT uq_test_form_course_kind UNIQUE (course_id, kind);


--
-- Name: test_form_item uq_test_form_item_question; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.test_form_item
    ADD CONSTRAINT uq_test_form_item_question UNIQUE (form_id, question_id);


--
-- Name: uq_mv_check_summary_mode; Type: INDEX; Schema: analytics; Owner: -
--

CREATE UNIQUE INDEX uq_mv_check_summary_mode ON analytics.mv_check_summary USING btree (experiment_mode);


--
-- Name: ix_account_consent_version; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_account_consent_version ON public.account USING btree (consent_version);


--
-- Name: ix_adaptation_event_attempt_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_adaptation_event_attempt_id ON public.adaptation_event USING btree (attempt_id);


--
-- Name: ix_adaptation_event_learner_section; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_adaptation_event_learner_section ON public.adaptation_event USING btree (learner_id, section_id, created_at);


--
-- Name: ix_adaptation_event_quiz_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_adaptation_event_quiz_id ON public.adaptation_event USING btree (quiz_id);


--
-- Name: ix_adaptation_event_rule; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_adaptation_event_rule ON public.adaptation_event USING btree (rule);


--
-- Name: ix_adaptation_event_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_adaptation_event_section_id ON public.adaptation_event USING btree (section_id);


--
-- Name: ix_attempt_learner_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_attempt_learner_created ON public.attempt USING btree (learner_id, created_at);


--
-- Name: ix_attempt_question_option; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_attempt_question_option ON public.attempt USING btree (question_id, selected_option);


--
-- Name: ix_attempt_quiz_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_attempt_quiz_id ON public.attempt USING btree (quiz_id);


--
-- Name: ix_chat_session_learner_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_chat_session_learner_started ON public.chat_session USING btree (learner_id, started_at);


--
-- Name: ix_chat_session_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_chat_session_section_id ON public.chat_session USING btree (section_id);


--
-- Name: ix_chunk_content_fts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_chunk_content_fts ON public.chunk USING gin (to_tsvector('english'::regconfig, content));


--
-- Name: ix_chunk_embedding_hnsw; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_chunk_embedding_hnsw ON public.chunk USING hnsw (embedding public.vector_cosine_ops);


--
-- Name: ix_course_owner_account_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_course_owner_account_id ON public.course USING btree (owner_account_id);


--
-- Name: ix_document_course_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_document_course_id ON public.document USING btree (course_id);


--
-- Name: ix_message_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_message_session_id ON public.message USING btree (session_id, id);


--
-- Name: ix_message_source_chunk_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_message_source_chunk_id ON public.message_source USING btree (chunk_id);


--
-- Name: ix_question_section_level; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_question_section_level ON public.question USING btree (section_id, level);


--
-- Name: ix_quiz_item_question_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_quiz_item_question_id ON public.quiz_item USING btree (question_id);


--
-- Name: ix_quiz_learner_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_quiz_learner_started ON public.quiz USING btree (learner_id, started_at);


--
-- Name: ix_quiz_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_quiz_section_id ON public.quiz USING btree (section_id);


--
-- Name: ix_review_item_first_attempt_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_review_item_first_attempt_id ON public.review_item USING btree (first_attempt_id);


--
-- Name: ix_review_item_last_attempt_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_review_item_last_attempt_id ON public.review_item USING btree (last_attempt_id);


--
-- Name: ix_review_item_open_due; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_review_item_open_due ON public.review_item USING btree (learner_id, due_at) WHERE (resolved_at IS NULL);


--
-- Name: ix_review_item_question_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_review_item_question_id ON public.review_item USING btree (question_id);


--
-- Name: ix_section_parent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_section_parent_id ON public.section USING btree (parent_id);


--
-- Name: ix_simulated_gap_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_simulated_gap_section_id ON public.simulated_gap USING btree (section_id);


--
-- Name: ix_test_form_item_question_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_test_form_item_question_id ON public.test_form_item USING btree (question_id);


--
-- Name: ix_topic_state_due_reviews; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_topic_state_due_reviews ON public.topic_state USING btree (learner_id, next_review_at) WHERE (next_review_at IS NOT NULL);


--
-- Name: ix_topic_state_learner_gaps; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_topic_state_learner_gaps ON public.topic_state USING btree (learner_id) WHERE (status = 'gap'::public.topic_status);


--
-- Name: ix_topic_state_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_topic_state_section_id ON public.topic_state USING btree (section_id);


--
-- Name: uq_attempt_quiz_question; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_attempt_quiz_question ON public.attempt USING btree (quiz_id, question_id) WHERE (quiz_id IS NOT NULL);


--
-- Name: uq_question_option_one_correct; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_question_option_one_correct ON public.question_option USING btree (question_id) WHERE is_correct;


--
-- Name: uq_quiz_one_open_check; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_quiz_one_open_check ON public.quiz USING btree (learner_id, section_id) WHERE ((kind = 'check'::public.quiz_kind) AND (status = 'in_progress'::public.quiz_status));


--
-- Name: v_check_session _RETURN; Type: RULE; Schema: analytics; Owner: -
--

CREATE OR REPLACE VIEW analytics.v_check_session AS
 SELECT q.id AS quiz_id,
    q.learner_id,
    l.experiment_mode,
    l.is_simulated,
    q.section_id AS topic_id,
    q.status,
    q.outcome,
    q.end_reason,
    q.started_at,
    q.ended_at,
    count(a.id) AS questions_answered,
    count(a.id) FILTER (WHERE a.is_correct) AS correct_answers
   FROM ((public.quiz q
     JOIN public.learner l ON ((l.id = q.learner_id)))
     LEFT JOIN public.attempt a ON ((a.quiz_id = q.id)))
  WHERE (q.kind = 'check'::public.quiz_kind)
  GROUP BY q.id, l.experiment_mode, l.is_simulated;


--
-- Name: v_test_result _RETURN; Type: RULE; Schema: analytics; Owner: -
--

CREATE OR REPLACE VIEW analytics.v_test_result AS
 SELECT q.learner_id,
    l.experiment_mode,
    l.is_simulated,
    q.kind AS test_kind,
    count(a.id) AS answered,
    count(a.id) FILTER (WHERE a.is_correct) AS correct,
    q.ended_at
   FROM ((public.quiz q
     JOIN public.learner l ON ((l.id = q.learner_id)))
     LEFT JOIN public.attempt a ON ((a.quiz_id = q.id)))
  WHERE (q.kind = ANY (ARRAY['pre_test'::public.quiz_kind, 'post_test'::public.quiz_kind]))
  GROUP BY q.id, l.experiment_mode, l.is_simulated;


--
-- Name: attempt trg_attempt_apply; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_attempt_apply AFTER INSERT ON public.attempt FOR EACH ROW EXECUTE FUNCTION public.trg_attempt_apply();


--
-- Name: attempt trg_attempt_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_attempt_immutable BEFORE UPDATE ON public.attempt FOR EACH ROW EXECUTE FUNCTION public.trg_attempt_immutable();


--
-- Name: attempt trg_attempt_review_list; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_attempt_review_list AFTER INSERT ON public.attempt FOR EACH ROW EXECUTE FUNCTION public.trg_attempt_review_list();


--
-- Name: attempt trg_attempt_validate; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_attempt_validate BEFORE INSERT ON public.attempt FOR EACH ROW EXECUTE FUNCTION public.trg_attempt_validate();


--
-- Name: question_option trg_option_keeps_correct; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER trg_option_keeps_correct AFTER DELETE OR UPDATE ON public.question_option DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.trg_option_keeps_correct();


--
-- Name: question trg_question_has_correct; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER trg_question_has_correct AFTER INSERT OR UPDATE ON public.question DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.trg_question_has_correct();


--
-- Name: quiz trg_quiz_adaptive_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_quiz_adaptive_only BEFORE INSERT OR UPDATE OF kind, learner_id ON public.quiz FOR EACH ROW EXECUTE FUNCTION public.trg_quiz_adaptive_only();


--
-- Name: simulated_gap trg_simulated_gap_validate; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_simulated_gap_validate BEFORE INSERT OR UPDATE ON public.simulated_gap FOR EACH ROW EXECUTE FUNCTION public.trg_simulated_gap_validate();


--
-- Name: topic_state trg_topic_state_touch; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_topic_state_touch BEFORE UPDATE ON public.topic_state FOR EACH ROW EXECUTE FUNCTION public.trg_touch_updated_at();


--
-- Name: account fk_account_consent_version_privacy_notice; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account
    ADD CONSTRAINT fk_account_consent_version_privacy_notice FOREIGN KEY (consent_version) REFERENCES public.privacy_notice(version) ON DELETE RESTRICT;


--
-- Name: adaptation_event fk_adaptation_event_attempt_id_attempt; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.adaptation_event
    ADD CONSTRAINT fk_adaptation_event_attempt_id_attempt FOREIGN KEY (attempt_id) REFERENCES public.attempt(id) ON DELETE CASCADE;


--
-- Name: adaptation_event fk_adaptation_event_learner_id_learner; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.adaptation_event
    ADD CONSTRAINT fk_adaptation_event_learner_id_learner FOREIGN KEY (learner_id) REFERENCES public.learner(id) ON DELETE CASCADE;


--
-- Name: adaptation_event fk_adaptation_event_quiz_id_quiz; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.adaptation_event
    ADD CONSTRAINT fk_adaptation_event_quiz_id_quiz FOREIGN KEY (quiz_id) REFERENCES public.quiz(id) ON DELETE CASCADE;


--
-- Name: adaptation_event fk_adaptation_event_rule_adaptation_rule; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.adaptation_event
    ADD CONSTRAINT fk_adaptation_event_rule_adaptation_rule FOREIGN KEY (rule) REFERENCES public.adaptation_rule(code) ON DELETE RESTRICT;


--
-- Name: adaptation_event fk_adaptation_event_section_id_section; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.adaptation_event
    ADD CONSTRAINT fk_adaptation_event_section_id_section FOREIGN KEY (section_id) REFERENCES public.section(id) ON DELETE CASCADE;


--
-- Name: attempt fk_attempt_learner_id_learner; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attempt
    ADD CONSTRAINT fk_attempt_learner_id_learner FOREIGN KEY (learner_id) REFERENCES public.learner(id) ON DELETE CASCADE;


--
-- Name: attempt fk_attempt_question_id_question; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attempt
    ADD CONSTRAINT fk_attempt_question_id_question FOREIGN KEY (question_id) REFERENCES public.question(id) ON DELETE CASCADE;


--
-- Name: attempt fk_attempt_quiz_id_quiz; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attempt
    ADD CONSTRAINT fk_attempt_quiz_id_quiz FOREIGN KEY (quiz_id) REFERENCES public.quiz(id) ON DELETE CASCADE;


--
-- Name: attempt fk_attempt_selected_option; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attempt
    ADD CONSTRAINT fk_attempt_selected_option FOREIGN KEY (question_id, selected_option) REFERENCES public.question_option(question_id, "position") ON DELETE CASCADE;


--
-- Name: chat_session fk_chat_session_learner_id_learner; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_session
    ADD CONSTRAINT fk_chat_session_learner_id_learner FOREIGN KEY (learner_id) REFERENCES public.learner(id) ON DELETE CASCADE;


--
-- Name: chat_session fk_chat_session_section_id_section; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_session
    ADD CONSTRAINT fk_chat_session_section_id_section FOREIGN KEY (section_id) REFERENCES public.section(id) ON DELETE CASCADE;


--
-- Name: chunk fk_chunk_section_id_section; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chunk
    ADD CONSTRAINT fk_chunk_section_id_section FOREIGN KEY (section_id) REFERENCES public.section(id) ON DELETE CASCADE;


--
-- Name: course fk_course_owner_account_id_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.course
    ADD CONSTRAINT fk_course_owner_account_id_account FOREIGN KEY (owner_account_id) REFERENCES public.account(id) ON DELETE CASCADE;


--
-- Name: document fk_document_course_id_course; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document
    ADD CONSTRAINT fk_document_course_id_course FOREIGN KEY (course_id) REFERENCES public.course(id) ON DELETE CASCADE;


--
-- Name: learner fk_learner_account_id_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learner
    ADD CONSTRAINT fk_learner_account_id_account FOREIGN KEY (account_id) REFERENCES public.account(id) ON DELETE CASCADE;


--
-- Name: message fk_message_session_id_chat_session; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message
    ADD CONSTRAINT fk_message_session_id_chat_session FOREIGN KEY (session_id) REFERENCES public.chat_session(id) ON DELETE CASCADE;


--
-- Name: message_source fk_message_source_chunk_id_chunk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_source
    ADD CONSTRAINT fk_message_source_chunk_id_chunk FOREIGN KEY (chunk_id) REFERENCES public.chunk(id) ON DELETE CASCADE;


--
-- Name: message_source fk_message_source_message_id_message; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_source
    ADD CONSTRAINT fk_message_source_message_id_message FOREIGN KEY (message_id) REFERENCES public.message(id) ON DELETE CASCADE;


--
-- Name: question_option fk_question_option_question_id_question; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_option
    ADD CONSTRAINT fk_question_option_question_id_question FOREIGN KEY (question_id) REFERENCES public.question(id) ON DELETE CASCADE;


--
-- Name: question fk_question_section_id_section; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question
    ADD CONSTRAINT fk_question_section_id_section FOREIGN KEY (section_id) REFERENCES public.section(id) ON DELETE CASCADE;


--
-- Name: quiz_item fk_quiz_item_question_id_question; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quiz_item
    ADD CONSTRAINT fk_quiz_item_question_id_question FOREIGN KEY (question_id) REFERENCES public.question(id) ON DELETE CASCADE;


--
-- Name: quiz_item fk_quiz_item_quiz_id_quiz; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quiz_item
    ADD CONSTRAINT fk_quiz_item_quiz_id_quiz FOREIGN KEY (quiz_id) REFERENCES public.quiz(id) ON DELETE CASCADE;


--
-- Name: quiz fk_quiz_learner_id_learner; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quiz
    ADD CONSTRAINT fk_quiz_learner_id_learner FOREIGN KEY (learner_id) REFERENCES public.learner(id) ON DELETE CASCADE;


--
-- Name: quiz fk_quiz_section_id_section; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quiz
    ADD CONSTRAINT fk_quiz_section_id_section FOREIGN KEY (section_id) REFERENCES public.section(id) ON DELETE CASCADE;


--
-- Name: review_item fk_review_item_first_attempt_id_attempt; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_item
    ADD CONSTRAINT fk_review_item_first_attempt_id_attempt FOREIGN KEY (first_attempt_id) REFERENCES public.attempt(id) ON DELETE SET NULL;


--
-- Name: review_item fk_review_item_last_attempt_id_attempt; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_item
    ADD CONSTRAINT fk_review_item_last_attempt_id_attempt FOREIGN KEY (last_attempt_id) REFERENCES public.attempt(id) ON DELETE SET NULL;


--
-- Name: review_item fk_review_item_learner_id_learner; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_item
    ADD CONSTRAINT fk_review_item_learner_id_learner FOREIGN KEY (learner_id) REFERENCES public.learner(id) ON DELETE CASCADE;


--
-- Name: review_item fk_review_item_question_id_question; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_item
    ADD CONSTRAINT fk_review_item_question_id_question FOREIGN KEY (question_id) REFERENCES public.question(id) ON DELETE CASCADE;


--
-- Name: section fk_section_document_id_document; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.section
    ADD CONSTRAINT fk_section_document_id_document FOREIGN KEY (document_id) REFERENCES public.document(id) ON DELETE CASCADE;


--
-- Name: section fk_section_parent_id_section; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.section
    ADD CONSTRAINT fk_section_parent_id_section FOREIGN KEY (parent_id) REFERENCES public.section(id) ON DELETE CASCADE;


--
-- Name: simulated_gap fk_simulated_gap_learner_id_learner; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.simulated_gap
    ADD CONSTRAINT fk_simulated_gap_learner_id_learner FOREIGN KEY (learner_id) REFERENCES public.learner(id) ON DELETE CASCADE;


--
-- Name: simulated_gap fk_simulated_gap_section_id_section; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.simulated_gap
    ADD CONSTRAINT fk_simulated_gap_section_id_section FOREIGN KEY (section_id) REFERENCES public.section(id) ON DELETE CASCADE;


--
-- Name: test_form fk_test_form_course_id_course; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.test_form
    ADD CONSTRAINT fk_test_form_course_id_course FOREIGN KEY (course_id) REFERENCES public.course(id) ON DELETE CASCADE;


--
-- Name: test_form_item fk_test_form_item_form_id_test_form; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.test_form_item
    ADD CONSTRAINT fk_test_form_item_form_id_test_form FOREIGN KEY (form_id) REFERENCES public.test_form(id) ON DELETE CASCADE;


--
-- Name: test_form_item fk_test_form_item_question_id_question; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.test_form_item
    ADD CONSTRAINT fk_test_form_item_question_id_question FOREIGN KEY (question_id) REFERENCES public.question(id);


--
-- Name: topic_state fk_topic_state_learner_id_learner; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.topic_state
    ADD CONSTRAINT fk_topic_state_learner_id_learner FOREIGN KEY (learner_id) REFERENCES public.learner(id) ON DELETE CASCADE;


--
-- Name: topic_state fk_topic_state_section_id_section; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.topic_state
    ADD CONSTRAINT fk_topic_state_section_id_section FOREIGN KEY (section_id) REFERENCES public.section(id) ON DELETE CASCADE;


--
-- Name: SCHEMA analytics; Type: ACL; Schema: -; Owner: -
--

GRANT USAGE ON SCHEMA analytics TO analytics_read;
GRANT USAGE ON SCHEMA analytics TO app_read;


--
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: -
--

REVOKE USAGE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO app_read;


--
-- Name: FUNCTION refresh_summaries(); Type: ACL; Schema: analytics; Owner: -
--

REVOKE ALL ON FUNCTION analytics.refresh_summaries() FROM PUBLIC;
GRANT ALL ON FUNCTION analytics.refresh_summaries() TO analytics_read;


--
-- Name: FUNCTION assert_question_has_correct(p_question uuid); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.assert_question_has_correct(p_question uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION public.assert_question_has_correct(p_question uuid) TO app_write;


--
-- Name: FUNCTION check_summary(p_quiz uuid, OUT total integer, OUT correct integer, OUT last_two_correct_high boolean, OUT last_two_wrong boolean, OUT last_two_correct_advanced boolean); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.check_summary(p_quiz uuid, OUT total integer, OUT correct integer, OUT last_two_correct_high boolean, OUT last_two_wrong boolean, OUT last_two_correct_advanced boolean) FROM PUBLIC;
GRANT ALL ON FUNCTION public.check_summary(p_quiz uuid, OUT total integer, OUT correct integer, OUT last_two_correct_high boolean, OUT last_two_wrong boolean, OUT last_two_correct_advanced boolean) TO app_write;
GRANT ALL ON FUNCTION public.check_summary(p_quiz uuid, OUT total integer, OUT correct integer, OUT last_two_correct_high boolean, OUT last_two_wrong boolean, OUT last_two_correct_advanced boolean) TO app_read;


--
-- Name: FUNCTION finish_check(p_quiz uuid, p_reason public.check_end_reason); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.finish_check(p_quiz uuid, p_reason public.check_end_reason) FROM PUBLIC;
GRANT ALL ON FUNCTION public.finish_check(p_quiz uuid, p_reason public.check_end_reason) TO app_write;


--
-- Name: FUNCTION mask_email(p_email text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.mask_email(p_email text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.mask_email(p_email text) TO app_write;
GRANT ALL ON FUNCTION public.mask_email(p_email text) TO app_read;


--
-- Name: FUNCTION next_level(p_level public.difficulty_level, p_correct boolean); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.next_level(p_level public.difficulty_level, p_correct boolean) FROM PUBLIC;
GRANT ALL ON FUNCTION public.next_level(p_level public.difficulty_level, p_correct boolean) TO app_write;


--
-- Name: FUNCTION quiz_review(p_quiz uuid); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.quiz_review(p_quiz uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION public.quiz_review(p_quiz uuid) TO app_write;
GRANT ALL ON FUNCTION public.quiz_review(p_quiz uuid) TO app_read;


--
-- Name: FUNCTION revision_offer(p_learner uuid, p_course uuid, p_absence_days integer, OUT offered boolean, OUT reason text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.revision_offer(p_learner uuid, p_course uuid, p_absence_days integer, OUT offered boolean, OUT reason text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.revision_offer(p_learner uuid, p_course uuid, p_absence_days integer, OUT offered boolean, OUT reason text) TO app_write;
GRANT ALL ON FUNCTION public.revision_offer(p_learner uuid, p_course uuid, p_absence_days integer, OUT offered boolean, OUT reason text) TO app_read;


--
-- Name: FUNCTION start_check(p_learner uuid, p_topic uuid); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.start_check(p_learner uuid, p_topic uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION public.start_check(p_learner uuid, p_topic uuid) TO app_write;


--
-- Name: FUNCTION stop_check(p_quiz uuid); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.stop_check(p_quiz uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION public.stop_check(p_quiz uuid) TO app_write;


--
-- Name: FUNCTION topic_of(p_section uuid); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.topic_of(p_section uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION public.topic_of(p_section uuid) TO app_write;
GRANT ALL ON FUNCTION public.topic_of(p_section uuid) TO app_read;
GRANT ALL ON FUNCTION public.topic_of(p_section uuid) TO analytics_read;


--
-- Name: FUNCTION topic_status_from_answers(p_total integer, p_correct integer, p_last_two_correct_high boolean); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.topic_status_from_answers(p_total integer, p_correct integer, p_last_two_correct_high boolean) FROM PUBLIC;
GRANT ALL ON FUNCTION public.topic_status_from_answers(p_total integer, p_correct integer, p_last_two_correct_high boolean) TO app_write;
GRANT ALL ON FUNCTION public.topic_status_from_answers(p_total integer, p_correct integer, p_last_two_correct_high boolean) TO app_read;


--
-- Name: FUNCTION trg_attempt_apply(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.trg_attempt_apply() FROM PUBLIC;


--
-- Name: FUNCTION trg_attempt_immutable(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.trg_attempt_immutable() FROM PUBLIC;


--
-- Name: FUNCTION trg_attempt_review_list(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.trg_attempt_review_list() FROM PUBLIC;


--
-- Name: FUNCTION trg_attempt_validate(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.trg_attempt_validate() FROM PUBLIC;


--
-- Name: FUNCTION trg_option_keeps_correct(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.trg_option_keeps_correct() FROM PUBLIC;


--
-- Name: FUNCTION trg_question_has_correct(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.trg_question_has_correct() FROM PUBLIC;


--
-- Name: FUNCTION trg_quiz_adaptive_only(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.trg_quiz_adaptive_only() FROM PUBLIC;


--
-- Name: FUNCTION trg_simulated_gap_validate(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.trg_simulated_gap_validate() FROM PUBLIC;


--
-- Name: FUNCTION trg_touch_updated_at(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.trg_touch_updated_at() FROM PUBLIC;


--
-- Name: TABLE v_check_session; Type: ACL; Schema: analytics; Owner: -
--

GRANT SELECT ON TABLE analytics.v_check_session TO analytics_read;


--
-- Name: TABLE mv_check_summary; Type: ACL; Schema: analytics; Owner: -
--

GRANT SELECT ON TABLE analytics.mv_check_summary TO analytics_read;


--
-- Name: TABLE chat_session; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.chat_session TO app_read;
GRANT INSERT,DELETE,UPDATE ON TABLE public.chat_session TO app_write;


--
-- Name: TABLE learner; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.learner TO app_read;
GRANT INSERT,DELETE,UPDATE ON TABLE public.learner TO app_write;


--
-- Name: TABLE message; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.message TO app_read;
GRANT INSERT,DELETE,UPDATE ON TABLE public.message TO app_write;


--
-- Name: TABLE message_source; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.message_source TO app_read;
GRANT INSERT,DELETE,UPDATE ON TABLE public.message_source TO app_write;


--
-- Name: TABLE v_answer_quality; Type: ACL; Schema: analytics; Owner: -
--

GRANT SELECT ON TABLE analytics.v_answer_quality TO analytics_read;


--
-- Name: TABLE attempt; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.attempt TO app_read;
GRANT INSERT,DELETE,UPDATE ON TABLE public.attempt TO app_write;


--
-- Name: TABLE question; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.question TO app_read;
GRANT INSERT,DELETE,UPDATE ON TABLE public.question TO app_write;


--
-- Name: TABLE quiz; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.quiz TO app_read;
GRANT INSERT,DELETE,UPDATE ON TABLE public.quiz TO app_write;


--
-- Name: TABLE v_attempt; Type: ACL; Schema: analytics; Owner: -
--

GRANT SELECT ON TABLE analytics.v_attempt TO analytics_read;


--
-- Name: TABLE v_confidence_calibration; Type: ACL; Schema: analytics; Owner: -
--

GRANT SELECT ON TABLE analytics.v_confidence_calibration TO analytics_read;


--
-- Name: TABLE document; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.document TO app_read;
GRANT INSERT,DELETE,UPDATE ON TABLE public.document TO app_write;


--
-- Name: TABLE section; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.section TO app_read;
GRANT INSERT,DELETE,UPDATE ON TABLE public.section TO app_write;


--
-- Name: TABLE simulated_gap; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.simulated_gap TO app_read;
GRANT INSERT,DELETE,UPDATE ON TABLE public.simulated_gap TO app_write;


--
-- Name: TABLE topic_state; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.topic_state TO app_read;
GRANT INSERT,DELETE,UPDATE ON TABLE public.topic_state TO app_write;


--
-- Name: TABLE v_gap_detection; Type: ACL; Schema: analytics; Owner: -
--

GRANT SELECT ON TABLE analytics.v_gap_detection TO analytics_read;


--
-- Name: TABLE v_test_result; Type: ACL; Schema: analytics; Owner: -
--

GRANT SELECT ON TABLE analytics.v_test_result TO analytics_read;


--
-- Name: TABLE v_topic_state; Type: ACL; Schema: analytics; Owner: -
--

GRANT SELECT ON TABLE analytics.v_topic_state TO analytics_read;


--
-- Name: TABLE account; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.account TO app_read;
GRANT INSERT,DELETE,UPDATE ON TABLE public.account TO app_write;


--
-- Name: TABLE account_masked; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.account_masked TO app_read;
GRANT INSERT,DELETE,UPDATE ON TABLE public.account_masked TO app_write;


--
-- Name: TABLE adaptation_event; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.adaptation_event TO app_read;
GRANT INSERT,DELETE,UPDATE ON TABLE public.adaptation_event TO app_write;


--
-- Name: SEQUENCE adaptation_event_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.adaptation_event_id_seq TO app_write;


--
-- Name: TABLE adaptation_rule; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.adaptation_rule TO app_read;


--
-- Name: SEQUENCE attempt_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.attempt_id_seq TO app_write;


--
-- Name: TABLE chunk; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.chunk TO app_read;
GRANT INSERT,DELETE,UPDATE ON TABLE public.chunk TO app_write;


--
-- Name: SEQUENCE chunk_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.chunk_id_seq TO app_write;


--
-- Name: TABLE course; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.course TO app_read;
GRANT INSERT,DELETE,UPDATE ON TABLE public.course TO app_write;


--
-- Name: SEQUENCE message_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.message_id_seq TO app_write;


--
-- Name: TABLE privacy_notice; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.privacy_notice TO app_read;


--
-- Name: TABLE question_option; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.question_option TO app_read;
GRANT INSERT,DELETE,UPDATE ON TABLE public.question_option TO app_write;


--
-- Name: TABLE quiz_item; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.quiz_item TO app_read;
GRANT INSERT,DELETE,UPDATE ON TABLE public.quiz_item TO app_write;


--
-- Name: TABLE review_item; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.review_item TO app_read;
GRANT INSERT,DELETE,UPDATE ON TABLE public.review_item TO app_write;


--
-- Name: TABLE test_form; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.test_form TO app_read;
GRANT INSERT,DELETE,UPDATE ON TABLE public.test_form TO app_write;


--
-- Name: TABLE test_form_item; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.test_form_item TO app_read;
GRANT INSERT,DELETE,UPDATE ON TABLE public.test_form_item TO app_write;


--
-- Name: DEFAULT PRIVILEGES FOR TABLES; Type: DEFAULT ACL; Schema: analytics; Owner: -
--

ALTER DEFAULT PRIVILEGES FOR ROLE admin IN SCHEMA analytics GRANT SELECT ON TABLES TO analytics_read;


--
-- Name: DEFAULT PRIVILEGES FOR SEQUENCES; Type: DEFAULT ACL; Schema: public; Owner: -
--

ALTER DEFAULT PRIVILEGES FOR ROLE admin IN SCHEMA public GRANT SELECT,USAGE ON SEQUENCES TO app_write;


--
-- Name: DEFAULT PRIVILEGES FOR TABLES; Type: DEFAULT ACL; Schema: public; Owner: -
--

ALTER DEFAULT PRIVILEGES FOR ROLE admin IN SCHEMA public GRANT SELECT ON TABLES TO app_read;
ALTER DEFAULT PRIVILEGES FOR ROLE admin IN SCHEMA public GRANT INSERT,DELETE,UPDATE ON TABLES TO app_write;


--
-- PostgreSQL database dump complete
--

\unrestrict zpZLLtquiEcLH7dcNCvTxJQIKkQ2NB8707Pc1WvueYAsInm4CfzwBPTqW8dCLao

