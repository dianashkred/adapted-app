import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.core.config import get_settings

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
settings = get_settings()


def alembic_cfg() -> Config:
    cfg = Config(os.path.join(BACKEND, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND, "alembic"))
    cfg.cmd_opts = type("o", (), {"x": [f"url={settings.test_migrator_database_url}"]})()
    return cfg


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    engine = create_engine(settings.test_migrator_database_url)
    with engine.connect() as c:
        c.execute(text("SET ROLE admin"))
        tables = c.execute(text("SELECT string_agg(quote_ident(tablename), ', ') FROM pg_tables "
                                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'")).scalar()
        if tables:
            c.execute(text(f"TRUNCATE {tables} CASCADE"))
        c.commit()
    engine.dispose()
    cfg = alembic_cfg()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(scope="session")
def app_engine():
    return create_engine(settings.test_database_url)


@pytest.fixture(scope="session")
def migrator_engine():
    return create_engine(settings.test_migrator_database_url)


@pytest.fixture
def conn(app_engine):
    with app_engine.connect() as c:
        trans = c.begin()
        yield c
        trans.rollback()


def scalar(conn, sql, **p):
    return conn.execute(text(sql), p).scalar_one()


@pytest.fixture
def make(conn):
    class Make:
        def account(self, role="student"):
            s = uuid.uuid4().hex
            return scalar(conn, """INSERT INTO account (auth_subject, email_hash, email_encrypted, role, consent_version, consent_given_at)
                                   VALUES (:s, :h, '\\x00', :r, '1.0', now()) RETURNING id""",
                          s=s, h=(s + s)[:64], r=role)

        def learner(self, mode=None, account=None):
            account = account or self.account()
            return scalar(conn, """INSERT INTO learner (account_id, is_participant, experiment_mode, mode_assigned_at)
                                   VALUES (:a, :p, CAST(:m AS experiment_mode), CASE WHEN CAST(:m AS text) IS NULL THEN NULL ELSE now() END)
                                   RETURNING id""", a=account, p=mode is not None, m=mode)

        def simulated_learner(self):
            return scalar(conn, "INSERT INTO learner (account_id, is_simulated) VALUES (NULL, true) RETURNING id")

        def course(self, owner=None, visibility="private"):
            owner = owner if owner is not None or visibility == "shared" else self.account()
            return scalar(conn, "INSERT INTO course (owner_account_id, title, visibility) VALUES (:o, 'Course', :v) RETURNING id",
                          o=owner, v=visibility)

        def document(self, course=None, **kw):
            course = course or self.course()
            h = uuid.uuid4().hex * 2
            values = dict(c=course, h=h, p=f"u/{h}.pdf", st="ready", size=1000) | kw
            return scalar(conn, """INSERT INTO document (course_id, file_name, mime_type, size_bytes, sha256, storage_path, status, processed_at)
                                   VALUES (:c, 'f.pdf', 'application/pdf', :size, :h, :p, :st, now()) RETURNING id""", **values)

        def topic(self, document=None):
            document = document or self.document()
            pos = scalar(conn, "SELECT coalesce(max(position), -1) + 1 FROM section WHERE document_id = :d", d=document)
            return scalar(conn, "INSERT INTO section (document_id, level, position, title) VALUES (:d, 1, :p, 'Topic') RETURNING id",
                          d=document, p=pos)

        def subsection(self, topic):
            doc = scalar(conn, "SELECT document_id FROM section WHERE id = :t", t=topic)
            pos = scalar(conn, "SELECT max(position) + 1 FROM section WHERE document_id = :d", d=doc)
            return scalar(conn, "INSERT INTO section (document_id, parent_id, level, position, title) VALUES (:d, :t, 2, :p, 'Sub') RETURNING id",
                          d=doc, t=topic, p=pos)

        def question(self, section, level="intermediate"):
            q = scalar(conn, """INSERT INTO question (section_id, level, kind, source, prompt, reference_answer)
                                VALUES (:s, :l, 'multiple_choice', 'generated', 'Q?', 'A') RETURNING id""", s=section, l=level)
            conn.execute(text("INSERT INTO question_option (question_id, position, option_text, is_correct) VALUES (:q, 1, 'right', true), (:q, 2, 'wrong', false)"),
                         dict(q=q))
            return q

    return Make()


@pytest.fixture
def check(conn, make):
    class Check:
        def __init__(self, learner, topic):
            self.learner, self.topic = learner, topic
            self.quiz = scalar(conn, "SELECT start_check(:l, :t)", l=learner, t=topic)
            self.position = 0
            self.levels = []

        @property
        def level(self):
            return scalar(conn, "SELECT current_level FROM topic_state WHERE learner_id = :l AND section_id = :t",
                          l=self.learner, t=self.topic)

        def answer(self, correct: bool, section=None, confidence="sure", question=None):
            level = self.level
            self.levels.append(level)
            q = question or make.question(section or self.topic, level)
            self.position += 1
            conn.execute(text("INSERT INTO quiz_item (quiz_id, position, question_id) VALUES (:z, :p, :q)"),
                         dict(z=self.quiz, p=self.position, q=q))
            conn.execute(text("""INSERT INTO attempt (learner_id, question_id, quiz_id, level, selected_option, is_correct, evaluated_by, confidence)
                                 VALUES (:l, :q, :z, :lvl, :o, :c, 'auto', CAST(:conf AS answer_confidence))"""),
                         dict(l=self.learner, q=q, z=self.quiz, lvl=level, o=1 if correct else 2, c=correct, conf=confidence))
            return self

        def answers(self, *results):
            for r in results:
                self.answer(r)
            return self

        @property
        def quiz_row(self):
            return conn.execute(text("SELECT status, outcome, end_reason FROM quiz WHERE id = :z"), dict(z=self.quiz)).one()

        @property
        def topic_status(self):
            return scalar(conn, "SELECT status FROM topic_state WHERE learner_id = :l AND section_id = :t", l=self.learner, t=self.topic)

    return Check
