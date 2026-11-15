import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.conftest import scalar


def new_quiz(conn, learner, kind, section=None, max_questions=None):
    max_questions = max_questions or {"revision": 10, "check": 6}.get(kind, 15)
    if kind == "check":
        return scalar(conn, "SELECT start_check(:l, :t)", l=learner, t=section)
    return scalar(conn, """INSERT INTO quiz (learner_id, section_id, kind, max_questions)
                           VALUES (:l, :s, CAST(:k AS quiz_kind), :m) RETURNING id""",
                  l=learner, s=section, k=kind, m=max_questions)


def answer(conn, learner, quiz, question, correct=True, confidence="sure"):
    pos = scalar(conn, "SELECT coalesce(max(position), 0) + 1 FROM quiz_item WHERE quiz_id = :z", z=quiz)
    conn.execute(text("INSERT INTO quiz_item (quiz_id, position, question_id) VALUES (:z, :p, :q)"), dict(z=quiz, p=pos, q=question))
    return scalar(conn, """INSERT INTO attempt (learner_id, question_id, quiz_id, level, selected_option, is_correct, evaluated_by, confidence)
                           VALUES (:l, :q, :z, 'intermediate', :o, :c, 'auto', CAST(:conf AS answer_confidence)) RETURNING id""",
                  l=learner, q=question, z=quiz, o=1 if correct else 2, c=correct, conf=confidence)


def free_text_question(conn, section):
    return scalar(conn, """INSERT INTO question (section_id, level, kind, source, prompt, reference_answer)
                           VALUES (:s, 'intermediate', 'free_text', 'curated', 'Explain', 'Reference') RETURNING id""", s=section)


def review_item(conn, learner, question):
    return conn.execute(text("SELECT * FROM review_item WHERE learner_id = :l AND question_id = :q"),
                        dict(l=learner, q=question)).one_or_none()


def fails(conn, match, fn, *args, **kw):
    with pytest.raises(DBAPIError, match=match):
        with conn.begin_nested():
            fn(*args, **kw)


@pytest.mark.parametrize("kind", ["check", "review", "topic_quiz", "revision"])
def test_confidence_is_required_in_learning_quizzes(conn, make, kind):
    learner, topic = make.learner(), make.topic()
    quiz = new_quiz(conn, learner, kind, topic if kind in ("check", "topic_quiz") else None)
    fails(conn, "confidence is required", answer, conn, learner, quiz, make.question(topic), True, None)
    answer(conn, learner, quiz, make.question(topic), True, "guessing")
    assert scalar(conn, "SELECT confidence FROM attempt WHERE quiz_id = :z", z=quiz) == "guessing"


@pytest.mark.parametrize("kind", ["pre_test", "post_test"])
def test_confidence_is_not_recorded_in_pre_and_post_tests(conn, make, kind):
    learner, topic = make.learner(mode="adaptive"), make.topic()
    quiz = new_quiz(conn, learner, kind, max_questions=5)
    fails(conn, "not recorded in pre- and post-tests", answer, conn, learner, quiz, make.question(topic), True, "sure")
    answer(conn, learner, quiz, make.question(topic), True, None)
    assert scalar(conn, "SELECT confidence FROM attempt WHERE quiz_id = :z", z=quiz) is None


def test_incorrect_answer_adds_review_item_due_after_one_day(conn, make):
    learner, topic = make.learner(), make.topic()
    q = make.question(topic)
    attempt = answer(conn, learner, new_quiz(conn, learner, "review"), q, correct=False, confidence="sure")
    item = review_item(conn, learner, q)
    assert item.reason == "incorrect" and item.resolved_at is None and item.times_added == 1
    assert item.first_attempt_id == item.last_attempt_id == attempt
    assert scalar(conn, "SELECT due_at - added_at FROM review_item WHERE learner_id = :l", l=learner).days == 1


@pytest.mark.parametrize("confidence", ["not_sure", "guessing"])
def test_correct_but_unsure_answer_adds_review_item_unsure(conn, make, confidence):
    learner, topic = make.learner(), make.topic()
    q = make.question(topic)
    answer(conn, learner, new_quiz(conn, learner, "topic_quiz", topic), q, correct=True, confidence=confidence)
    assert review_item(conn, learner, q).reason == "unsure"


def test_correct_and_sure_answer_adds_nothing(conn, make):
    learner, topic = make.learner(), make.topic()
    answer(conn, learner, new_quiz(conn, learner, "review"), make.question(topic), correct=True, confidence="sure")
    assert scalar(conn, "SELECT count(*) FROM review_item WHERE learner_id = :l", l=learner) == 0


def test_later_correct_and_sure_answer_resolves_the_item(conn, make, check):
    learner, topic = make.learner(), make.topic()
    q = make.question(topic)
    check(learner, topic).answer(False, question=q)
    answer(conn, learner, new_quiz(conn, learner, "review"), q, correct=True, confidence="not_sure")
    item = review_item(conn, learner, q)
    assert (item.reason, item.resolved_at, item.times_added) == ("unsure", None, 2)
    last = answer(conn, learner, new_quiz(conn, learner, "topic_quiz", topic), q, correct=True, confidence="sure")
    item = review_item(conn, learner, q)
    assert item.resolved_at is not None and item.last_attempt_id == last


def test_resolved_item_comes_back_after_a_new_mistake(conn, make):
    learner, topic = make.learner(), make.topic()
    q = make.question(topic)
    answer(conn, learner, new_quiz(conn, learner, "review"), q, correct=False)
    answer(conn, learner, new_quiz(conn, learner, "review"), q, correct=True, confidence="sure")
    answer(conn, learner, new_quiz(conn, learner, "review"), q, correct=False)
    item = review_item(conn, learner, q)
    assert item.resolved_at is None and item.times_added == 2


def test_open_due_items_use_the_partial_index(conn):
    assert scalar(conn, "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_review_item_open_due'").endswith("WHERE (resolved_at IS NULL)")


def test_mode_a_stores_confidence_but_gets_no_review_list(conn, make, check):
    learner, topic = make.learner(mode="plain_rag"), make.topic()
    c = check(learner, topic).answer(False, confidence="guessing")
    assert scalar(conn, "SELECT confidence FROM attempt WHERE quiz_id = :z", z=c.quiz) == "guessing"
    assert scalar(conn, "SELECT count(*) FROM review_item WHERE learner_id = :l", l=learner) == 0


def test_mode_b_gets_the_review_list(conn, make, check):
    learner, topic = make.learner(mode="adaptive"), make.topic()
    check(learner, topic).answer(False)
    assert scalar(conn, "SELECT count(*) FROM review_item WHERE learner_id = :l", l=learner) == 1


@pytest.mark.parametrize("kind", ["pre_test", "post_test"])
def test_pre_and_post_tests_never_add_review_items(conn, make, kind):
    learner, topic = make.learner(mode="adaptive"), make.topic()
    answer(conn, learner, new_quiz(conn, learner, kind, max_questions=5), make.question(topic), correct=False, confidence=None)
    assert scalar(conn, "SELECT count(*) FROM review_item WHERE learner_id = :l", l=learner) == 0
    assert scalar(conn, "SELECT count(*) FROM topic_state WHERE learner_id = :l", l=learner) == 0


@pytest.mark.parametrize("kind", ["topic_quiz", "revision"])
def test_mode_a_cannot_get_topic_or_revision_quizzes(conn, make, kind):
    learner, topic = make.learner(mode="plain_rag"), make.topic()
    fails(conn, "not available in experiment mode A", new_quiz, conn, learner, kind, topic)


@pytest.mark.parametrize("kind", ["topic_quiz", "revision"])
def test_topic_and_revision_quizzes_accept_only_multiple_choice(conn, make, kind):
    learner, topic = make.learner(), make.topic()
    quiz = new_quiz(conn, learner, kind, topic)
    fails(conn, "accepts only multiple-choice questions", answer, conn, learner, quiz, free_text_question(conn, topic))


@pytest.mark.parametrize("kind", ["topic_quiz", "revision"])
def test_topic_and_revision_quizzes_do_not_change_topic_state(conn, make, check, kind):
    learner, topic = make.learner(), make.topic()
    check(learner, topic).answers(True, True, True)
    snapshot = "SELECT status, current_level, attempts_count, correct_count, consecutive_errors, last_attempt_at, next_review_at, updated_at " \
               "FROM topic_state WHERE learner_id = :l AND section_id = :t"
    before = conn.execute(text(snapshot), dict(l=learner, t=topic)).one()
    events_before = scalar(conn, "SELECT count(*) FROM adaptation_event WHERE learner_id = :l", l=learner)
    quiz = new_quiz(conn, learner, kind, topic)
    for _ in range(3):
        answer(conn, learner, quiz, make.question(topic), correct=False, confidence="guessing")
    assert conn.execute(text(snapshot), dict(l=learner, t=topic)).one() == before
    assert scalar(conn, "SELECT count(*) FROM adaptation_event WHERE learner_id = :l", l=learner) == events_before
    assert scalar(conn, "SELECT outcome FROM quiz WHERE id = :z", z=quiz) is None


@pytest.mark.parametrize("kind,limit", [("topic_quiz", 3), ("revision", 10)])
def test_topic_and_revision_quizzes_complete_automatically(conn, make, kind, limit):
    learner, topic = make.learner(), make.topic()
    quiz = new_quiz(conn, learner, kind, topic, max_questions=limit)
    for i in range(limit):
        assert scalar(conn, "SELECT status FROM quiz WHERE id = :z", z=quiz) == "in_progress"
        answer(conn, learner, quiz, make.question(topic), correct=i % 2 == 0)
    row = conn.execute(text("SELECT status, ended_at, end_reason FROM quiz WHERE id = :z"), dict(z=quiz)).one()
    assert row.status == "completed" and row.ended_at is not None and row.end_reason is None
    fails(conn, "already closed", answer, conn, learner, quiz, make.question(topic))


@pytest.mark.parametrize("kind,section,max_q", [
    ("topic_quiz", False, 15),
    ("topic_quiz", True, 31),
    ("revision", False, 9),
    ("revision", False, 21),
    ("check", True, 7),
])
def test_quiz_size_rules(conn, make, kind, section, max_q):
    learner, topic = make.learner(), make.topic()
    with pytest.raises(IntegrityError):
        with conn.begin_nested():
            conn.execute(text("INSERT INTO quiz (learner_id, section_id, kind, max_questions) VALUES (:l, :s, CAST(:k AS quiz_kind), :m)"),
                         dict(l=learner, s=topic if section else None, k=kind, m=max_q))


def test_quiz_review_returns_exactly_the_incorrect_and_unsure_answers(conn, make):
    learner, topic = make.learner(), make.topic()
    quiz = new_quiz(conn, learner, "topic_quiz", topic)
    plan = [(True, "sure"), (False, "sure"), (True, "not_sure"), (True, "guessing"), (False, "guessing"), (True, "sure")]
    attempts = [answer(conn, learner, quiz, make.question(topic), c, conf) for c, conf in plan]
    rows = conn.execute(text("SELECT * FROM quiz_review(:z)"), dict(z=quiz)).all()
    assert [r.attempt_id for r in rows] == [attempts[1], attempts[2], attempts[3], attempts[4]]
    assert [r.item_position for r in rows] == [2, 3, 4, 5]
    assert all(r.correct_option == 1 and r.correct_text == "right" for r in rows)
    assert rows[0].selected_text == "wrong" and rows[0].confidence == "sure" and rows[0].is_correct is False
    assert rows[1].selected_text == "right" and rows[1].confidence == "not_sure"


def test_quiz_review_of_a_check(conn, make, check):
    c = check(make.learner(), make.topic()).answer(True).answer(False, confidence="not_sure")
    rows = conn.execute(text("SELECT is_correct, confidence FROM quiz_review(:z)"), dict(z=c.quiz)).all()
    assert [tuple(r) for r in rows] == [(False, "not_sure")]


@pytest.fixture
def course3(conn, make):
    learner = make.learner()
    doc = make.document()
    topics = [make.topic(doc) for _ in range(3)]
    course = scalar(conn, "SELECT course_id FROM document WHERE id = :d", d=doc)
    conn.execute(text("INSERT INTO topic_state (learner_id, section_id, status) VALUES (:l, :t, 'mastered')"), dict(l=learner, t=topics[0]))
    return learner, course, topics


def offer(conn, learner, course, days=7):
    return tuple(conn.execute(text("SELECT offered, reason FROM revision_offer(:l, :c, :d)"), dict(l=learner, c=course, d=days)).one())


def test_revision_offered_after_absence(conn, course3):
    learner, course, _ = course3
    conn.execute(text("UPDATE learner SET last_seen_at = now() - interval '8 days' WHERE id = :l"), dict(l=learner))
    assert offer(conn, learner, course) == (True, "absence")
    assert offer(conn, learner, course, days=10) == (True, "new_topic")


def test_revision_offered_before_a_new_topic_once(conn, make, course3):
    learner, course, topics = course3
    conn.execute(text("UPDATE learner SET last_seen_at = now() WHERE id = :l"), dict(l=learner))
    assert offer(conn, learner, course) == (True, "new_topic")
    rev = new_quiz(conn, learner, "revision")
    answer(conn, learner, rev, make.question(topics[0]))
    assert offer(conn, learner, course) == (False, None)


def test_revision_not_offered_without_studied_topics(conn, make):
    learner, doc = make.learner(), make.document()
    make.topic(doc)
    course = scalar(conn, "SELECT course_id FROM document WHERE id = :d", d=doc)
    conn.execute(text("UPDATE learner SET last_seen_at = now() - interval '30 days' WHERE id = :l"), dict(l=learner))
    assert offer(conn, learner, course) == (False, None)


def test_revision_not_offered_when_reminders_are_off(conn, course3):
    learner, course, _ = course3
    conn.execute(text("UPDATE learner SET revision_reminders = false, last_seen_at = now() - interval '8 days' WHERE id = :l"), dict(l=learner))
    assert offer(conn, learner, course) == (False, None)


def test_revision_not_offered_in_mode_a(conn, make):
    learner, doc = make.learner(mode="plain_rag"), make.document()
    topic = make.topic(doc)
    make.topic(doc)
    course = scalar(conn, "SELECT course_id FROM document WHERE id = :d", d=doc)
    conn.execute(text("INSERT INTO topic_state (learner_id, section_id, status) VALUES (:l, :t, 'gap')"), dict(l=learner, t=topic))
    conn.execute(text("UPDATE learner SET last_seen_at = now() - interval '8 days' WHERE id = :l"), dict(l=learner))
    assert offer(conn, learner, course) == (False, None)


def test_preference_defaults_and_values(conn, make):
    learner = make.learner()
    row = conn.execute(text("SELECT ui_theme, revision_reminders, last_seen_at FROM learner WHERE id = :l"), dict(l=learner)).one()
    assert tuple(row) == ("system", True, None)
    with pytest.raises(DBAPIError):
        with conn.begin_nested():
            conn.execute(text("UPDATE learner SET ui_theme = 'blue' WHERE id = :l"), dict(l=learner))


def test_simulated_learner_without_account_is_allowed(conn, make):
    sim = make.simulated_learner()
    assert scalar(conn, "SELECT account_id IS NULL AND is_simulated FROM learner WHERE id = :l", l=sim)


def test_real_learner_without_account_is_rejected(conn):
    with pytest.raises(IntegrityError, match="ck_learner_account_iff_real"):
        with conn.begin_nested():
            conn.execute(text("INSERT INTO learner (account_id) VALUES (NULL)"))


def test_simulated_learner_with_account_is_rejected(conn, make):
    with pytest.raises(IntegrityError, match="ck_learner_account_iff_real"):
        with conn.begin_nested():
            conn.execute(text("INSERT INTO learner (account_id, is_simulated) VALUES (:a, true)"), dict(a=make.account()))


def test_simulated_gap_only_for_simulated_learners_and_topics(conn, make):
    topic = make.topic()
    sql = "INSERT INTO simulated_gap (learner_id, section_id) VALUES (:l, :s)"
    fails(conn, "only for simulated learners", conn.execute, text(sql), dict(l=make.learner(), s=topic))
    sim = make.simulated_learner()
    fails(conn, "not a topic", conn.execute, text(sql), dict(l=sim, s=make.subsection(topic)))
    conn.execute(text(sql), dict(l=sim, s=topic))
    assert scalar(conn, "SELECT count(*) FROM simulated_gap WHERE learner_id = :l", l=sim) == 1


def test_gap_detection_view_gives_the_confusion_matrix(migrator_engine):
    with migrator_engine.connect() as m:
        tx = m.begin()
        try:
            m.execute(text("SET LOCAL ROLE admin"))
            course = scalar(m, "INSERT INTO course (title, visibility) VALUES ('K2', 'shared') RETURNING id")
            doc = scalar(m, """INSERT INTO document (course_id, file_name, mime_type, size_bytes, sha256, storage_path, status, processed_at)
                               VALUES (:c, 'k2.pdf', 'application/pdf', 10, repeat('e', 64), 'k2/k2.pdf', 'ready', now()) RETURNING id""", c=course)
            t_tp, t_fp, t_fn, t_tn = (scalar(m, "INSERT INTO section (document_id, level, position, title) VALUES (:d, 1, :p, 'T') RETURNING id",
                                             d=doc, p=p) for p in range(4))
            sim = scalar(m, "INSERT INTO learner (account_id, is_simulated) VALUES (NULL, true) RETURNING id")
            for t in (t_tp, t_fn):
                m.execute(text("INSERT INTO simulated_gap (learner_id, section_id) VALUES (:l, :s)"), dict(l=sim, s=t))
            for t, status in ((t_tp, "gap"), (t_fp, "gap"), (t_fn, "mastered")):
                m.execute(text("INSERT INTO topic_state (learner_id, section_id, status) VALUES (:l, :s, CAST(:st AS topic_status))"),
                          dict(l=sim, s=t, st=status))
            rows = dict(m.execute(text("SELECT topic_id, result FROM analytics.v_gap_detection WHERE learner_id = :l"), dict(l=sim)).all())
            assert rows == {t_tp: "TP", t_fp: "FP", t_fn: "FN", t_tn: "TN"}
            assert scalar(m, "SELECT bool_and(l.is_simulated) FROM analytics.v_gap_detection g JOIN learner l ON l.id = g.learner_id")
        finally:
            tx.rollback()
