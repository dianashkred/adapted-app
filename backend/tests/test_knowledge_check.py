"""Topic knowledge check: max 6 questions, first Intermediate, early end rules, US-11 outcome."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.conftest import scalar


def events(conn, quiz):
    return conn.execute(text("SELECT rule FROM adaptation_event WHERE quiz_id = :q ORDER BY id"), dict(q=quiz)).scalars().all()


def test_first_question_is_intermediate_even_if_level_was_basic(conn, make, check):
    learner, topic = make.learner(), make.topic()
    conn.execute(text("INSERT INTO topic_state (learner_id, section_id, current_level) VALUES (:l, :t, 'basic')"), dict(l=learner, t=topic))
    assert check(learner, topic).level == "intermediate"


def test_all_correct_ends_after_two_advanced(conn, make, check):
    c = check(make.learner(), make.topic()).answers(True, True, True)
    assert c.levels == ["intermediate", "advanced", "advanced"]
    assert tuple(c.quiz_row) == ("completed", "mastered", "success_sequence")
    assert c.topic_status == "mastered"
    assert events(conn, c.quiz) == ["check_started", "level_up", "topic_mastered"]


def test_two_errors_in_a_row_end_with_gap_and_basic_chapter(conn, make, check):
    c = check(make.learner(), make.topic()).answers(False, False)
    assert c.levels == ["intermediate", "basic"]
    assert tuple(c.quiz_row) == ("completed", "gap", "two_consecutive_errors")
    assert c.topic_status == "gap"
    assert events(conn, c.quiz) == ["check_started", "level_down", "basic_chapter_link", "topic_gap"]
    assert scalar(conn, "SELECT next_review_at > now() FROM topic_state WHERE learner_id = :l", l=c.learner)


def test_one_error_then_success(conn, make, check):
    c = check(make.learner(), make.topic()).answers(False, True, True, True)
    assert c.levels == ["intermediate", "basic", "intermediate", "advanced"]
    assert c.quiz_row.status == "in_progress"
    c.answer(True)
    assert tuple(c.quiz_row) == ("completed", "mastered", "success_sequence")


def test_error_on_advanced_goes_back_to_intermediate(make, check):
    c = check(make.learner(), make.topic()).answers(True, False)
    assert c.levels == ["intermediate", "advanced"]
    assert c.level == "intermediate"
    assert c.quiz_row.status == "in_progress"


def test_limit_with_last_two_correct_is_mastered_by_us11(make, check):
    # 4/6 = 66.7 % < 75 %, but the last two answers are correct at Intermediate/Advanced (US-11)
    c = check(make.learner(), make.topic()).answers(True, False, True, False, True, True)
    assert tuple(c.quiz_row) == ("completed", "mastered", "question_limit")


def test_limit_below_75_percent_is_gap(make, check):
    c = check(make.learner(), make.topic()).answers(True, False, True, True, False, True)
    # levels: I(c) A(w) I(c) A(c) A(w) I(c): last two = (wrong, correct) -> 4/6 -> gap
    assert tuple(c.quiz_row) == ("completed", "gap", "question_limit")


def test_mode_a_keeps_level_and_runs_to_the_limit(conn, make, check):
    c = check(make.learner(mode="plain_rag"), make.topic()).answers(True, True, True, False, False, True)
    assert set(c.levels) == {"intermediate"}
    assert tuple(c.quiz_row)[0::2] == ("completed", "question_limit")
    assert "level_up" not in events(conn, c.quiz)


def test_stop_after_one_answer_is_not_checked(conn, make, check):
    c = check(make.learner(), make.topic()).answer(True)
    assert scalar(conn, "SELECT stop_check(:q)", q=c.quiz) == "not_checked"
    assert tuple(c.quiz_row) == ("completed", "not_checked", "stopped_by_learner")
    assert c.topic_status == "not_checked"


def test_stop_after_three_answers_uses_us11(conn, make, check):
    c = check(make.learner(), make.topic()).answers(True, False, True)   # 2/3 = 66 %, last two = (wrong, correct)
    assert scalar(conn, "SELECT stop_check(:q)", q=c.quiz) == "gap"
    assert tuple(c.quiz_row) == ("completed", "gap", "stopped_by_learner")


def test_no_answer_after_the_check_is_closed(conn, make, check):
    c = check(make.learner(), make.topic()).answers(True, True, True)
    with pytest.raises(DBAPIError, match="already closed"):
        c.answer(True)


def test_question_must_be_part_of_the_quiz(conn, make, check):
    c = check(make.learner(), make.topic())
    q = make.question(c.topic)
    with pytest.raises(DBAPIError, match="not part of quiz"):
        conn.execute(text("INSERT INTO attempt (learner_id, question_id, quiz_id, level, selected_option, is_correct, evaluated_by) VALUES (:l, :q, :z, 'intermediate', 1, true, 'auto')"),
                     dict(l=c.learner, q=q, z=c.quiz))


def test_answer_of_another_learner_is_rejected(conn, make, check):
    c = check(make.learner(), make.topic())
    q = make.question(c.topic)
    conn.execute(text("INSERT INTO quiz_item (quiz_id, position, question_id) VALUES (:z, 1, :q)"), dict(z=c.quiz, q=q))
    with pytest.raises(DBAPIError, match="different learners"):
        conn.execute(text("INSERT INTO attempt (learner_id, question_id, quiz_id, level, selected_option, is_correct, evaluated_by) VALUES (:l, :q, :z, 'intermediate', 1, true, 'auto')"),
                     dict(l=make.learner(), q=q, z=c.quiz))


def test_check_only_on_a_topic(conn, make):
    topic = make.topic()
    with pytest.raises(DBAPIError, match="not a topic"):
        conn.execute(text("SELECT start_check(:l, :s)"), dict(l=make.learner(), s=make.subsection(topic)))


def test_start_twice_resumes_the_open_check(conn, make):
    learner, topic = make.learner(), make.topic()
    first = scalar(conn, "SELECT start_check(:l, :t)", l=learner, t=topic)
    assert scalar(conn, "SELECT start_check(:l, :t)", l=learner, t=topic) == first


def test_question_of_a_subsection_counts_for_its_topic(conn, make, check):
    topic = make.topic()
    c = check(make.learner(), topic)
    c.answer(True, section=make.subsection(topic))
    assert scalar(conn, "SELECT attempts_count FROM topic_state WHERE learner_id = :l AND section_id = :t", l=c.learner, t=topic) == 1


def test_pre_test_does_not_change_the_learner_model(conn, make):
    learner, topic = make.learner(mode="adaptive"), make.topic()
    quiz = scalar(conn, "INSERT INTO quiz (learner_id, kind, max_questions) VALUES (:l, 'pre_test', 5) RETURNING id", l=learner)
    q = make.question(topic)
    conn.execute(text("INSERT INTO quiz_item (quiz_id, position, question_id) VALUES (:z, 1, :q)"), dict(z=quiz, q=q))
    conn.execute(text("INSERT INTO attempt (learner_id, question_id, quiz_id, level, selected_option, is_correct, evaluated_by) VALUES (:l, :q, :z, 'intermediate', 1, true, 'auto')"),
                 dict(l=learner, q=q, z=quiz))
    assert scalar(conn, "SELECT count(*) FROM topic_state WHERE learner_id = :l", l=learner) == 0


def test_attempts_cannot_be_changed(conn, make, check):
    c = check(make.learner(), make.topic()).answer(True)
    with pytest.raises(DBAPIError, match="cannot be changed"):
        conn.execute(text("UPDATE attempt SET is_correct = false WHERE quiz_id = :z"), dict(z=c.quiz))


@pytest.mark.parametrize("total,correct,last_two,expected", [
    (0, 0, False, "not_checked"), (1, 1, False, "not_checked"), (2, 2, True, "mastered"),
    (4, 3, False, "mastered"), (6, 4, False, "gap"), (6, 4, True, "mastered"), (2, 0, False, "gap"),
])
def test_us11_rule(conn, total, correct, last_two, expected):
    assert scalar(conn, "SELECT topic_status_from_answers(:t, :c, :l)", t=total, c=correct, l=last_two) == expected


@pytest.mark.parametrize("level,correct,expected", [
    ("basic", True, "intermediate"), ("intermediate", True, "advanced"), ("advanced", True, "advanced"),
    ("advanced", False, "intermediate"), ("intermediate", False, "basic"), ("basic", False, "basic"),
])
def test_us12_next_level(conn, level, correct, expected):
    assert scalar(conn, "SELECT next_level(:l, :c)", l=level, c=correct) == expected
