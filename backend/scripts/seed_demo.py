import hashlib
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from app.core.config import get_settings
from app.core.crypto import email_hash, encrypt_email

DIM = 384
rng = random.Random(42)
NOW = datetime.now(timezone.utc)


def vec() -> str:
    v = [rng.uniform(-1, 1) for _ in range(DIM)]
    n = sum(x * x for x in v) ** 0.5
    return "[" + ",".join(f"{x / n:.5f}" for x in v) + "]"


def one(conn: Connection, sql: str, **params):
    return conn.execute(text(sql), params).scalar_one()


def account(conn, email: str, role: str = "student", participant: bool = False, mode: str | None = None):
    acc = one(conn, """INSERT INTO account (auth_subject, email_hash, email_encrypted, role, consent_version, consent_given_at)
                       VALUES (:sub, :h, :enc, :role, '1.0', :t) RETURNING id""",
              sub=f"demo-{email.split('@')[0]}", h=email_hash(email), enc=encrypt_email(email), role=role,
              t=NOW - timedelta(days=10))
    learner = one(conn, """INSERT INTO learner (account_id, is_participant, experiment_mode, mode_assigned_at)
                           VALUES (:a, :p, CAST(:m AS experiment_mode), CASE WHEN CAST(:m AS text) IS NULL THEN NULL ELSE now() END)
                           RETURNING id""", a=acc, p=participant, m=mode)
    return acc, learner


def question(conn, section, level, n, kind="multiple_choice"):
    q = one(conn, """INSERT INTO question (section_id, level, kind, source, prompt, reference_answer)
                     VALUES (:s, :l, :k, 'generated', :p, :r) RETURNING id""",
            s=section, l=level, k=kind, p=f"[{level}] Demo question {n}", r=f"Reference answer {n}")
    if kind == "multiple_choice":
        for pos in range(1, 5):
            conn.execute(text("INSERT INTO question_option (question_id, position, option_text, is_correct) VALUES (:q, :p, :t, :c)"),
                         dict(q=q, p=pos, t=f"Option {pos}", c=pos == 1))
    return q


class Bank:
    def __init__(self, conn, topic):
        self.by_level = {lvl: [question(conn, topic, lvl, f"{lvl[:1]}{i}") for i in range(6)]
                         for lvl in ("basic", "intermediate", "advanced")}

    def take(self, level, used):
        return next(q for q in self.by_level[level] if q not in used)


def run_check(conn, learner, topic, bank: Bank, answers: list[bool], stop=False, confidence: list[str] | None = None):
    quiz = one(conn, "SELECT start_check(:l, :t)", l=learner, t=topic)
    used = []
    confidence = confidence or ["sure"] * len(answers)
    for pos, correct in enumerate(answers, start=1):
        status = one(conn, "SELECT status FROM quiz WHERE id = :q", q=quiz)
        if status != "in_progress":
            break
        level = one(conn, "SELECT current_level FROM topic_state WHERE learner_id = :l AND section_id = :t", l=learner, t=topic)
        q = bank.take(level, used); used.append(q)
        conn.execute(text("INSERT INTO quiz_item (quiz_id, position, question_id) VALUES (:z, :p, :q)"), dict(z=quiz, p=pos, q=q))
        conn.execute(text("""INSERT INTO attempt (learner_id, question_id, quiz_id, level, selected_option, is_correct, evaluated_by, feedback, confidence)
                             VALUES (:l, :q, :z, :lvl, :opt, :c, 'auto', :f, CAST(:conf AS answer_confidence))"""),
                     dict(l=learner, q=q, z=quiz, lvl=level, opt=1 if correct else 2, c=correct, conf=confidence[pos - 1],
                          f=None if correct and confidence[pos - 1] == "sure"
                          else "Correct answer and explanation with a link to the source chapter."))
    if stop:
        conn.execute(text("SELECT stop_check(:q)"), dict(q=quiz))
    return quiz


def practice(conn, learner, kind, topic, questions, answers: list[tuple[bool, str]]):
    quiz = one(conn, "INSERT INTO quiz (learner_id, section_id, kind, max_questions) VALUES (:l, :s, :k, :m) RETURNING id",
               l=learner, s=topic, k=kind, m=len(questions))
    for pos, (q, (correct, conf)) in enumerate(zip(questions, answers), start=1):
        level = one(conn, "SELECT level FROM question WHERE id = :q", q=q)
        conn.execute(text("INSERT INTO quiz_item (quiz_id, position, question_id) VALUES (:z, :p, :q)"), dict(z=quiz, p=pos, q=q))
        conn.execute(text("""INSERT INTO attempt (learner_id, question_id, quiz_id, level, selected_option, is_correct, evaluated_by, feedback, confidence)
                             VALUES (:l, :q, :z, :lvl, :opt, :c, 'auto', :f, CAST(:conf AS answer_confidence))"""),
                     dict(l=learner, q=q, z=quiz, lvl=level, opt=1 if correct else 2, c=correct, conf=conf,
                          f=None if correct and conf == "sure" else "Correct answer and explanation with a link to the source chapter."))
    return quiz


def main(url: str | None = None) -> None:
    engine = create_engine(url or get_settings().database_url)
    with engine.begin() as conn:
        if one(conn, "SELECT count(*) FROM account"):
            print("demo data already present — nothing to do")
            return

        admin_acc, _ = account(conn, "admin@adapted.demo", role="admin")
        _, alice = account(conn, "alice@adapted.demo")
        _, ben = account(conn, "ben@adapted.demo", participant=True, mode="plain_rag")
        _, chloe = account(conn, "chloe@adapted.demo", participant=True, mode="adaptive")
        _, dan = account(conn, "dan@adapted.demo", participant=True)
        eva_acc, eva = account(conn, "eva@adapted.demo")

        corpus = one(conn, "INSERT INTO course (owner_account_id, title, visibility) VALUES (NULL, 'The Modern JavaScript Tutorial — Part 1', 'shared') RETURNING id")
        doc = one(conn, """INSERT INTO document (course_id, file_name, mime_type, size_bytes, sha256, storage_path, status, page_count, processed_at)
                           VALUES (:c, 'javascript-part-1.pdf', 'application/pdf', 8421337, :h, :p, 'ready', 697, now()) RETURNING id""",
                  c=corpus, h=hashlib.sha256(b"js-part-1").hexdigest(), p=f"shared/{corpus}/javascript-part-1.pdf")
        topics = {}
        position = 0
        for title, subs in [("JavaScript Fundamentals", ["Variables", "Data types", "Loops"]),
                            ("Objects: the basics", ["Objects", "Object references", "Garbage collection"]),
                            ("Data types", ["Methods of primitives", "Arrays", "Map and Set"]),
                            ("Advanced working with functions", ["Recursion", "Closures"])]:
            topic = one(conn, "INSERT INTO section (document_id, level, position, title, page_start, page_end) VALUES (:d, 1, :p, :t, :a, :b) RETURNING id",
                        d=doc, p=position, t=title, a=position * 40 + 1, b=position * 40 + 40)
            topics[title] = topic
            position += 1
            for i, sub in enumerate(subs):
                sec = one(conn, "INSERT INTO section (document_id, parent_id, level, position, title) VALUES (:d, :pa, 2, :p, :t) RETURNING id",
                          d=doc, pa=topic, p=position, t=sub)
                position += 1
                for k in range(3):
                    conn.execute(text("INSERT INTO chunk (section_id, position, content, token_count, page, embedding) VALUES (:s, :p, :c, :n, :pg, CAST(:e AS vector))"),
                                 dict(s=sec, p=k, c=f"{sub}: demo passage {k + 1} of the evaluation corpus.", n=rng.randint(200, 380), pg=i + 1, e=vec()))

        empty_course = one(conn, "INSERT INTO course (owner_account_id, title) VALUES (:o, 'History notes (no files yet)') RETURNING id", o=eva_acc)
        bio = one(conn, "INSERT INTO course (owner_account_id, title) VALUES (:o, 'Biology — cell structure') RETURNING id", o=eva_acc)
        conn.execute(text("""INSERT INTO document (course_id, file_name, mime_type, size_bytes, sha256, status, error_message) VALUES
            (:c, 'scan.pdf', 'application/pdf', 1048576, :h1, 'failed', 'The PDF has no text layer (scanned document). OCR is out of scope.'),
            (:c, 'lecture-2.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 52311, :h2, 'processing', NULL)"""),
            dict(c=bio, h1=hashlib.sha256(b"scan").hexdigest(), h2=hashlib.sha256(b"lecture-2").hexdigest()))

        banks = {t: Bank(conn, s) for t, s in topics.items()}
        fund, objs, dtypes, funcs = (topics[t] for t in topics)
        b = list(banks.values())

        run_check(conn, alice, fund, b[0], [True, True, True])
        alice_objs = run_check(conn, alice, objs, b[1], [False, False])
        run_check(conn, alice, dtypes, b[2], [False, True, True, True, True],
                  confidence=["sure", "not_sure", "guessing", "sure", "sure"])
        run_check(conn, ben, fund, b[0], [True, False, True, True, False, True])
        run_check(conn, chloe, fund, b[0], [True, False, True, False, True, True])
        run_check(conn, chloe, objs, b[1], [True], stop=True)
        run_check(conn, alice, funcs, b[3], [True])

        missed = one(conn, "SELECT question_id FROM attempt WHERE quiz_id = :z AND NOT is_correct ORDER BY id LIMIT 1", z=alice_objs)
        review = one(conn, "INSERT INTO quiz (learner_id, kind, max_questions) VALUES (:l, 'review', 5) RETURNING id", l=alice)
        for pos, (q, conf) in enumerate([(missed, "sure"), (b[2].by_level["basic"][5], "not_sure")], start=1):
            conn.execute(text("INSERT INTO quiz_item (quiz_id, position, question_id) VALUES (:z, :p, :q)"), dict(z=review, p=pos, q=q))
            conn.execute(text("""INSERT INTO attempt (learner_id, question_id, quiz_id, level, selected_option, is_correct, evaluated_by, confidence)
                                 VALUES (:l, :q, :z, 'basic', 1, true, 'auto', CAST(:conf AS answer_confidence))"""),
                         dict(l=alice, q=q, z=review, conf=conf))
        conn.execute(text("UPDATE quiz SET status = 'completed', ended_at = now() WHERE id = :z"), dict(z=review))

        mixed = [q for i in range(6) for q in (b[0].by_level["basic"][i], b[0].by_level["intermediate"][i], b[0].by_level["advanced"][i])]
        practice(conn, alice, "topic_quiz", fund, mixed[:15],
                 [(True, "sure")] * 10 + [(False, "sure"), (True, "guessing"), (False, "not_sure"), (True, "sure"), (True, "not_sure")])

        earlier = [b[0].by_level["basic"][i] for i in range(5)] + [b[1].by_level["intermediate"][i] for i in range(5)]
        practice(conn, chloe, "revision", None, earlier,
                 [(True, "sure")] * 6 + [(False, "guessing"), (True, "not_sure"), (False, "sure"), (True, "sure")])

        conn.execute(text("UPDATE learner SET ui_theme = 'dark', revision_reminders = false, last_seen_at = now() WHERE id = :l"), dict(l=eva))
        conn.execute(text("UPDATE learner SET last_seen_at = now() - interval '9 days' WHERE id = :l"), dict(l=alice))
        conn.execute(text("UPDATE learner SET last_seen_at = now() WHERE id IN (:b, :c)"), dict(b=ben, c=chloe))

        for truth, checks in (([objs], [(fund, 0, [True, True, True]), (objs, 1, [False, False])]),
                              ([], [(dtypes, 2, [False, False])]),
                              ([funcs], [(funcs, 3, [True, True, True])])):
            sim = one(conn, "INSERT INTO learner (account_id, is_simulated) VALUES (NULL, true) RETURNING id")
            for topic in truth:
                conn.execute(text("INSERT INTO simulated_gap (learner_id, section_id) VALUES (:l, :s)"), dict(l=sim, s=topic))
            for topic, bank_no, answers in checks:
                run_check(conn, sim, topic, b[bank_no], answers)

        for kind in ("pre_test", "post_test"):
            form = one(conn, "INSERT INTO test_form (course_id, kind, title) VALUES (:c, :k, :t) RETURNING id",
                       c=corpus, k=kind, t=f"{kind.replace('_', '-').title()} — JavaScript Part 1")
            items = []
            for i in range(5):
                q = one(conn, """INSERT INTO question (section_id, level, kind, source, prompt, reference_answer)
                                 VALUES (:s, 'intermediate', 'free_text', 'curated', :p, 'Curated reference answer') RETURNING id""",
                        s=list(topics.values())[i % 4], p=f"{kind} question {i + 1}")
                conn.execute(text("INSERT INTO test_form_item (form_id, position, question_id) VALUES (:f, :p, :q)"), dict(f=form, p=i + 1, q=q))
                items.append(q)
            for learner, score in ((ben, 2 if kind == "pre_test" else 3), (chloe, 2 if kind == "pre_test" else 4)):
                quiz = one(conn, "INSERT INTO quiz (learner_id, kind, max_questions) VALUES (:l, :k, 5) RETURNING id", l=learner, k=kind)
                for pos, q in enumerate(items, start=1):
                    conn.execute(text("INSERT INTO quiz_item (quiz_id, position, question_id) VALUES (:z, :p, :q)"), dict(z=quiz, p=pos, q=q))
                    conn.execute(text("""INSERT INTO attempt (learner_id, question_id, quiz_id, level, answer_text, is_correct, evaluated_by)
                                         VALUES (:l, :q, :z, 'intermediate', 'Free-text answer of the participant', :c, 'llm')"""),
                                 dict(l=learner, q=q, z=quiz, c=pos <= score))
                conn.execute(text("UPDATE quiz SET status = 'completed', ended_at = now() WHERE id = :z"), dict(z=quiz))

        chunk_ids = conn.execute(text("SELECT id FROM chunk ORDER BY id LIMIT 3")).scalars().all()
        sess = one(conn, "INSERT INTO chat_session (learner_id, section_id, mode) VALUES (:l, :s, 'free_question') RETURNING id", l=alice, s=fund)
        conn.execute(text("INSERT INTO message (session_id, role, content) VALUES (:s, 'user', 'What is the difference between let and var?')"), dict(s=sess))
        ans = one(conn, """INSERT INTO message (session_id, role, content, model, latency_ms, prompt_tokens, completion_tokens, max_similarity)
                           VALUES (:s, 'assistant', 'Grounded demo answer with sources.', 'groq:llama-3.3-70b-versatile', 2140, 1630, 210, 0.81) RETURNING id""", s=sess)
        for rank, cid in enumerate(chunk_ids, start=1):
            conn.execute(text("INSERT INTO message_source (message_id, chunk_id, rank, similarity) VALUES (:m, :c, :r, :sim)"),
                         dict(m=ans, c=cid, r=rank, sim=round(0.81 - rank * 0.05, 2)))
        conn.execute(text("INSERT INTO message (session_id, role, content) VALUES (:s, 'user', 'Who won the 2018 football World Cup?')"), dict(s=sess))
        conn.execute(text("""INSERT INTO message (session_id, role, content, model, latency_ms, max_similarity, is_refusal)
                             VALUES (:s, 'assistant', 'This topic is not covered in the course materials.', NULL, 95, 0.21, true)"""), dict(s=sess))
        conn.execute(text("INSERT INTO chat_session (learner_id, section_id, mode, current_step, total_steps) VALUES (:l, :s, 'guided', 2, 5)"),
                     dict(l=chloe, s=objs))

    with engine.connect() as conn:
        counts = {t: one(conn, f"SELECT count(*) FROM {t}") for t in
                  ("account", "learner", "course", "document", "section", "chunk", "question", "quiz", "attempt", "topic_state",
                   "adaptation_event", "review_item", "simulated_gap", "message")}
    print("demo data created:", ", ".join(f"{k}={v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
