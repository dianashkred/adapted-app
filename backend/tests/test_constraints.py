"""Integrity: constraints, deferred triggers, cascades (US-03), transactions."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.conftest import scalar


def savepoint_fails(conn, sql, params=None, exc=IntegrityError):
    with pytest.raises(exc):
        with conn.begin_nested():
            conn.execute(text(sql), params or {})


def test_document_rules(conn, make):
    course = make.course()
    savepoint_fails(conn, "INSERT INTO document (course_id, file_name, mime_type, size_bytes, sha256) VALUES (:c, 'big.pdf', 'application/pdf', 52428801, repeat('a', 64))", dict(c=course))
    savepoint_fails(conn, "INSERT INTO document (course_id, file_name, mime_type, size_bytes, sha256) VALUES (:c, 'x.exe', 'application/x-msdownload', 10, repeat('a', 64))", dict(c=course))
    savepoint_fails(conn, "INSERT INTO document (course_id, file_name, mime_type, size_bytes, sha256, status) VALUES (:c, 'f.pdf', 'application/pdf', 10, repeat('a', 64), 'failed')", dict(c=course))
    savepoint_fails(conn, "INSERT INTO document (course_id, file_name, mime_type, size_bytes, sha256, status, processed_at) VALUES (:c, 'f.pdf', 'application/pdf', 10, repeat('a', 64), 'ready', now())", dict(c=course))


def test_same_file_is_not_indexed_twice_in_a_course(conn, make):
    course = make.course()
    make.document(course, h="b" * 64, p="u/one.pdf")
    with pytest.raises(IntegrityError):
        with conn.begin_nested():
            make.document(course, h="b" * 64, p="u/two.pdf")


def test_private_course_needs_an_owner(conn):
    savepoint_fails(conn, "INSERT INTO course (title, visibility) VALUES ('x', 'private')")


def test_section_tree_rules(conn, make):
    doc = make.document()
    savepoint_fails(conn, "INSERT INTO section (document_id, level, position, title) VALUES (:d, 2, 0, 'orphan')", dict(d=doc))
    savepoint_fails(conn, "INSERT INTO section (document_id, level, position, title, page_start, page_end) VALUES (:d, 1, 0, 'x', 10, 5)", dict(d=doc))


def test_multiple_choice_needs_exactly_one_correct_option(conn, make):
    topic = make.topic()
    with pytest.raises(DBAPIError, match="no correct option"):
        with conn.begin_nested():
            conn.execute(text("INSERT INTO question (section_id, level, kind, source, prompt, reference_answer) VALUES (:s, 'basic', 'multiple_choice', 'generated', 'Q', 'A')"), dict(s=topic))
            conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    q = make.question(topic)
    savepoint_fails(conn, "INSERT INTO question_option (question_id, position, option_text, is_correct) VALUES (:q, 3, 'also right', true)", dict(q=q))


def test_attempt_has_exactly_one_answer_form(conn, make):
    learner, q = make.learner(), make.question(make.topic())
    savepoint_fails(conn, "INSERT INTO attempt (learner_id, question_id, level, selected_option, answer_text, is_correct, evaluated_by) VALUES (:l, :q, 'basic', 1, 'text', true, 'auto')", dict(l=learner, q=q))
    savepoint_fails(conn, "INSERT INTO attempt (learner_id, question_id, level, selected_option, is_correct, evaluated_by) VALUES (:l, :q, 'basic', 9, true, 'auto')", dict(l=learner, q=q))


def test_experiment_mode_only_for_participants(conn, make):
    savepoint_fails(conn, "INSERT INTO learner (account_id, is_participant, experiment_mode, mode_assigned_at) VALUES (:a, false, 'adaptive', now())", dict(a=make.account()))


def test_email_hash_must_be_hex(conn):
    savepoint_fails(conn, "INSERT INTO account (auth_subject, email_hash, email_encrypted, consent_version, consent_given_at) VALUES ('s', 'not-a-hash', '\\x00', '1.0', now())")


def test_unknown_consent_version_is_rejected(conn):
    savepoint_fails(conn, "INSERT INTO account (auth_subject, email_hash, email_encrypted, consent_version, consent_given_at) VALUES ('s', repeat('c', 64), '\\x00', '9.9', now())")


def test_user_question_length_is_limited(conn, make):
    session = scalar(conn, "INSERT INTO chat_session (learner_id, section_id, mode) VALUES (:l, :s, 'free_question') RETURNING id", l=make.learner(), s=make.topic())
    savepoint_fails(conn, "INSERT INTO message (session_id, role, content) VALUES (:s, 'user', repeat('x', 1001))", dict(s=session))


def test_deleting_an_account_deletes_all_learning_data(conn, make, check):
    account = make.account()
    learner = make.learner(account=account)
    course = make.course(owner=account)
    c = check(learner, make.topic(make.document(course))).answers(True, True, True)
    conn.execute(text("DELETE FROM account WHERE id = :a"), dict(a=account))
    for table, col in (("learner", "id"), ("quiz", "learner_id"), ("attempt", "learner_id"),
                       ("topic_state", "learner_id"), ("adaptation_event", "learner_id")):
        assert scalar(conn, f"SELECT count(*) FROM {table} WHERE {col} = :l", l=learner) == 0
    assert scalar(conn, "SELECT count(*) FROM course WHERE id = :c", c=course) == 0


def test_answer_and_learner_model_are_one_transaction(conn, make, check):
    """If the trigger fails, the answer is not stored either (all or nothing)."""
    c = check(make.learner(), make.topic()).answers(True, True, True)   # closed
    before = scalar(conn, "SELECT count(*) FROM attempt WHERE quiz_id = :z", z=c.quiz)
    with pytest.raises(DBAPIError):
        with conn.begin_nested():
            c.answer(True)
    assert scalar(conn, "SELECT count(*) FROM attempt WHERE quiz_id = :z", z=c.quiz) == before
