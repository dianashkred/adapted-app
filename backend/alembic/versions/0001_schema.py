"""Initial schema: 20 tables in 3NF with keys, constraints and indexes (TZ section 7).

Revision ID: 0001
Revises: 
Create Date: 2026-11-14 17:21:16.444920
"""
from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy


revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")  # installed by the superuser; no-op here
    op.create_table('adaptation_rule',
    sa.Column('code', sa.String(length=40), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.CheckConstraint("code ~ '^[a-z_]+$'", name=op.f('ck_adaptation_rule_code_format')),
    sa.PrimaryKeyConstraint('code', name=op.f('pk_adaptation_rule'))
    )
    op.create_table('privacy_notice',
    sa.Column('version', sa.String(length=20), nullable=False),
    sa.Column('published_on', sa.Date(), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.CheckConstraint("version ~ '^[0-9]+\\.[0-9]+$'", name=op.f('ck_privacy_notice_version_format')),
    sa.PrimaryKeyConstraint('version', name=op.f('pk_privacy_notice'))
    )
    op.create_table('account',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('auth_subject', sa.String(length=64), nullable=False),
    sa.Column('email_hash', sa.String(length=64), nullable=False),
    sa.Column('email_encrypted', sa.LargeBinary(), nullable=False),
    sa.Column('role', sa.Enum('student', 'admin', name='account_role'), server_default='student', nullable=False),
    sa.Column('consent_version', sa.String(length=20), nullable=False),
    sa.Column('consent_given_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("consent_given_at <= now() + interval '1 minute'", name=op.f('ck_account_consent_not_in_future')),
    sa.CheckConstraint("email_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_account_email_hash_hex')),
    sa.ForeignKeyConstraint(['consent_version'], ['privacy_notice.version'], name=op.f('fk_account_consent_version_privacy_notice'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_account')),
    sa.UniqueConstraint('auth_subject', name=op.f('uq_account_auth_subject')),
    sa.UniqueConstraint('email_hash', name=op.f('uq_account_email_hash'))
    )
    op.create_index(op.f('ix_account_consent_version'), 'account', ['consent_version'], unique=False)
    op.create_table('course',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('owner_account_id', sa.UUID(), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('language', sa.String(length=10), server_default=sa.text("'en'"), nullable=False),
    sa.Column('visibility', sa.Enum('private', 'shared', name='course_visibility'), server_default='private', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("owner_account_id IS NOT NULL OR visibility = 'shared'", name=op.f('ck_course_private_course_has_owner')),
    sa.CheckConstraint('length(btrim(title)) > 0', name=op.f('ck_course_title_not_blank')),
    sa.ForeignKeyConstraint(['owner_account_id'], ['account.id'], name=op.f('fk_course_owner_account_id_account'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_course'))
    )
    op.create_index(op.f('ix_course_owner_account_id'), 'course', ['owner_account_id'], unique=False)
    op.create_table('learner',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('is_participant', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('experiment_mode', sa.Enum('plain_rag', 'adaptive', name='experiment_mode'), nullable=True),
    sa.Column('mode_assigned_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('starting_level', sa.Enum('basic', 'intermediate', 'advanced', name='difficulty_level'), server_default='intermediate', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('(experiment_mode IS NULL) = (mode_assigned_at IS NULL)', name=op.f('ck_learner_mode_and_time_together')),
    sa.CheckConstraint('experiment_mode IS NULL OR is_participant', name=op.f('ck_learner_mode_only_for_participants')),
    sa.ForeignKeyConstraint(['account_id'], ['account.id'], name=op.f('fk_learner_account_id_account'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_learner')),
    sa.UniqueConstraint('account_id', name=op.f('uq_learner_account_id'))
    )
    op.create_table('document',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('course_id', sa.UUID(), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('mime_type', sa.String(length=100), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('storage_path', sa.String(length=500), nullable=True),
    sa.Column('status', sa.Enum('processing', 'ready', 'failed', name='document_status'), server_default='processing', nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('page_count', sa.Integer(), nullable=True),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("mime_type IN ('application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'text/plain', 'text/markdown')", name=op.f('ck_document_allowed_mime')),
    sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f('ck_document_sha256_hex')),
    sa.CheckConstraint("status <> 'failed' OR error_message IS NOT NULL", name=op.f('ck_document_failed_has_reason')),
    sa.CheckConstraint("status <> 'ready' OR (processed_at IS NOT NULL AND storage_path IS NOT NULL)", name=op.f('ck_document_ready_is_complete')),
    sa.CheckConstraint('page_count IS NULL OR page_count > 0', name=op.f('ck_document_page_count_positive')),
    sa.CheckConstraint('size_bytes > 0 AND size_bytes <= 52428800', name=op.f('ck_document_size_limit')),
    sa.ForeignKeyConstraint(['course_id'], ['course.id'], name=op.f('fk_document_course_id_course'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_document')),
    sa.UniqueConstraint('course_id', 'sha256', name='uq_document_course_file'),
    sa.UniqueConstraint('storage_path', name=op.f('uq_document_storage_path'))
    )
    op.create_index(op.f('ix_document_course_id'), 'document', ['course_id'], unique=False)
    op.create_table('test_form',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('course_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.Enum('pre_test', 'post_test', name='test_kind'), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['course_id'], ['course.id'], name=op.f('fk_test_form_course_id_course'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_test_form')),
    sa.UniqueConstraint('course_id', 'kind', name='uq_test_form_course_kind')
    )
    op.create_table('section',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('parent_id', sa.UUID(), nullable=True),
    sa.Column('level', sa.SmallInteger(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('page_start', sa.Integer(), nullable=True),
    sa.Column('page_end', sa.Integer(), nullable=True),
    sa.CheckConstraint('(level = 1) = (parent_id IS NULL)', name=op.f('ck_section_only_topics_have_no_parent')),
    sa.CheckConstraint('level BETWEEN 1 AND 6', name=op.f('ck_section_level_range')),
    sa.CheckConstraint('page_end IS NULL OR page_start IS NULL OR page_end >= page_start', name=op.f('ck_section_page_order')),
    sa.CheckConstraint('position >= 0', name=op.f('ck_section_position_non_negative')),
    sa.ForeignKeyConstraint(['document_id'], ['document.id'], name=op.f('fk_section_document_id_document'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['parent_id'], ['section.id'], name=op.f('fk_section_parent_id_section'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_section')),
    sa.UniqueConstraint('document_id', 'position', name='uq_section_document_position')
    )
    op.create_index(op.f('ix_section_parent_id'), 'section', ['parent_id'], unique=False)
    op.create_table('chat_session',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('learner_id', sa.UUID(), nullable=False),
    sa.Column('section_id', sa.UUID(), nullable=False),
    sa.Column('mode', sa.Enum('guided', 'free_question', name='chat_mode'), nullable=False),
    sa.Column('current_step', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('total_steps', sa.SmallInteger(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("(mode = 'guided') = (total_steps IS NOT NULL)", name=op.f('ck_chat_session_steps_only_for_guided')),
    sa.CheckConstraint('current_step >= 0 AND (total_steps IS NULL OR current_step <= total_steps)', name=op.f('ck_chat_session_step_range')),
    sa.CheckConstraint('ended_at IS NULL OR ended_at >= started_at', name=op.f('ck_chat_session_time_order')),
    sa.ForeignKeyConstraint(['learner_id'], ['learner.id'], name=op.f('fk_chat_session_learner_id_learner'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['section_id'], ['section.id'], name=op.f('fk_chat_session_section_id_section'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_chat_session'))
    )
    op.create_index('ix_chat_session_learner_started', 'chat_session', ['learner_id', 'started_at'], unique=False)
    op.create_index(op.f('ix_chat_session_section_id'), 'chat_session', ['section_id'], unique=False)
    op.create_table('chunk',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('section_id', sa.UUID(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('token_count', sa.Integer(), nullable=False),
    sa.Column('page', sa.Integer(), nullable=True),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('length(content) > 0', name=op.f('ck_chunk_content_not_empty')),
    sa.CheckConstraint('token_count BETWEEN 1 AND 2000', name=op.f('ck_chunk_token_count_range')),
    sa.ForeignKeyConstraint(['section_id'], ['section.id'], name=op.f('fk_chunk_section_id_section'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_chunk')),
    sa.UniqueConstraint('section_id', 'position', name='uq_chunk_section_position')
    )
    op.create_index('ix_chunk_content_fts', 'chunk', [sa.literal_column("to_tsvector('english', content)")], unique=False, postgresql_using='gin')
    op.create_index('ix_chunk_embedding_hnsw', 'chunk', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_table('question',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('section_id', sa.UUID(), nullable=False),
    sa.Column('level', sa.Enum('basic', 'intermediate', 'advanced', name='difficulty_level'), nullable=False),
    sa.Column('kind', sa.Enum('multiple_choice', 'free_text', name='question_kind'), nullable=False),
    sa.Column('source', sa.Enum('generated', 'curated', name='question_source'), nullable=False),
    sa.Column('prompt', sa.Text(), nullable=False),
    sa.Column('reference_answer', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('length(btrim(prompt)) > 0', name=op.f('ck_question_prompt_not_blank')),
    sa.CheckConstraint('length(btrim(reference_answer)) > 0', name=op.f('ck_question_reference_not_blank')),
    sa.ForeignKeyConstraint(['section_id'], ['section.id'], name=op.f('fk_question_section_id_section'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_question'))
    )
    op.create_index('ix_question_section_level', 'question', ['section_id', 'level'], unique=False)
    op.create_table('quiz',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('learner_id', sa.UUID(), nullable=False),
    sa.Column('section_id', sa.UUID(), nullable=True),
    sa.Column('kind', sa.Enum('check', 'review', 'pre_test', 'post_test', name='quiz_kind'), nullable=False),
    sa.Column('status', sa.Enum('in_progress', 'completed', 'abandoned', name='quiz_status'), server_default='in_progress', nullable=False),
    sa.Column('max_questions', sa.SmallInteger(), server_default=sa.text('6'), nullable=False),
    sa.Column('outcome', sa.Enum('not_checked', 'gap', 'mastered', name='topic_status'), nullable=True),
    sa.Column('end_reason', sa.Enum('success_sequence', 'two_consecutive_errors', 'question_limit', 'stopped_by_learner', name='check_end_reason'), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("(status = 'in_progress') = (ended_at IS NULL)", name=op.f('ck_quiz_ended_iff_closed')),
    sa.CheckConstraint("kind <> 'check' OR (section_id IS NOT NULL AND max_questions <= 6)", name=op.f('ck_quiz_check_is_per_topic')),
    sa.CheckConstraint("kind <> 'check' OR status <> 'completed' OR (outcome IS NOT NULL AND end_reason IS NOT NULL)", name=op.f('ck_quiz_completed_check_has_result')),
    sa.CheckConstraint("kind = 'check' OR end_reason IS NULL", name=op.f('ck_quiz_end_reason_only_for_checks')),
    sa.CheckConstraint('ended_at IS NULL OR ended_at >= started_at', name=op.f('ck_quiz_time_order')),
    sa.CheckConstraint('max_questions BETWEEN 1 AND 30', name=op.f('ck_quiz_max_questions_range')),
    sa.ForeignKeyConstraint(['learner_id'], ['learner.id'], name=op.f('fk_quiz_learner_id_learner'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['section_id'], ['section.id'], name=op.f('fk_quiz_section_id_section'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_quiz'))
    )
    op.create_index('ix_quiz_learner_started', 'quiz', ['learner_id', 'started_at'], unique=False)
    op.create_index(op.f('ix_quiz_section_id'), 'quiz', ['section_id'], unique=False)
    op.create_index('uq_quiz_one_open_check', 'quiz', ['learner_id', 'section_id'], unique=True, postgresql_where=sa.text("kind = 'check' AND status = 'in_progress'"))
    op.create_table('topic_state',
    sa.Column('learner_id', sa.UUID(), nullable=False),
    sa.Column('section_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.Enum('not_checked', 'gap', 'mastered', name='topic_status'), server_default='not_checked', nullable=False),
    sa.Column('current_level', sa.Enum('basic', 'intermediate', 'advanced', name='difficulty_level'), server_default='intermediate', nullable=False),
    sa.Column('attempts_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('correct_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('consecutive_errors', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('next_review_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('attempts_count >= 0 AND correct_count >= 0 AND correct_count <= attempts_count', name=op.f('ck_topic_state_counters_consistent')),
    sa.CheckConstraint('consecutive_errors >= 0', name=op.f('ck_topic_state_consecutive_errors_non_negative')),
    sa.ForeignKeyConstraint(['learner_id'], ['learner.id'], name=op.f('fk_topic_state_learner_id_learner'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['section_id'], ['section.id'], name=op.f('fk_topic_state_section_id_section'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('learner_id', 'section_id', name=op.f('pk_topic_state'))
    )
    op.create_index('ix_topic_state_due_reviews', 'topic_state', ['learner_id', 'next_review_at'], unique=False, postgresql_where=sa.text('next_review_at IS NOT NULL'))
    op.create_index('ix_topic_state_learner_gaps', 'topic_state', ['learner_id'], unique=False, postgresql_where=sa.text("status = 'gap'"))
    op.create_index(op.f('ix_topic_state_section_id'), 'topic_state', ['section_id'], unique=False)
    op.create_table('message',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('role', sa.Enum('user', 'assistant', name='message_role'), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('model', sa.String(length=100), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('prompt_tokens', sa.Integer(), nullable=True),
    sa.Column('completion_tokens', sa.Integer(), nullable=True),
    sa.Column('max_similarity', sa.Float(), nullable=True),
    sa.Column('is_refusal', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role = 'assistant' OR (model IS NULL AND latency_ms IS NULL AND NOT is_refusal)", name=op.f('ck_message_llm_fields_only_for_answers')),
    sa.CheckConstraint("role = 'assistant' OR length(content) <= 1000", name=op.f('ck_message_question_length')),
    sa.CheckConstraint('latency_ms IS NULL OR latency_ms >= 0', name=op.f('ck_message_latency_non_negative')),
    sa.CheckConstraint('length(content) > 0', name=op.f('ck_message_content_not_empty')),
    sa.CheckConstraint('max_similarity IS NULL OR max_similarity BETWEEN -1 AND 1', name=op.f('ck_message_similarity_range')),
    sa.ForeignKeyConstraint(['session_id'], ['chat_session.id'], name=op.f('fk_message_session_id_chat_session'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_message'))
    )
    op.create_index('ix_message_session_id', 'message', ['session_id', 'id'], unique=False)
    op.create_table('question_option',
    sa.Column('question_id', sa.UUID(), nullable=False),
    sa.Column('position', sa.SmallInteger(), nullable=False),
    sa.Column('option_text', sa.Text(), nullable=False),
    sa.Column('is_correct', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.CheckConstraint('length(btrim(option_text)) > 0', name=op.f('ck_question_option_text_not_blank')),
    sa.CheckConstraint('position BETWEEN 1 AND 6', name=op.f('ck_question_option_position_range')),
    sa.ForeignKeyConstraint(['question_id'], ['question.id'], name=op.f('fk_question_option_question_id_question'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('question_id', 'position', name=op.f('pk_question_option'))
    )
    op.create_index('uq_question_option_one_correct', 'question_option', ['question_id'], unique=True, postgresql_where=sa.text('is_correct'))
    op.create_table('quiz_item',
    sa.Column('quiz_id', sa.UUID(), nullable=False),
    sa.Column('position', sa.SmallInteger(), nullable=False),
    sa.Column('question_id', sa.UUID(), nullable=False),
    sa.CheckConstraint('position >= 1', name=op.f('ck_quiz_item_position_positive')),
    sa.ForeignKeyConstraint(['question_id'], ['question.id'], name=op.f('fk_quiz_item_question_id_question'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['quiz_id'], ['quiz.id'], name=op.f('fk_quiz_item_quiz_id_quiz'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('quiz_id', 'position', name=op.f('pk_quiz_item')),
    sa.UniqueConstraint('quiz_id', 'question_id', name='uq_quiz_item_question')
    )
    op.create_index(op.f('ix_quiz_item_question_id'), 'quiz_item', ['question_id'], unique=False)
    op.create_table('test_form_item',
    sa.Column('form_id', sa.UUID(), nullable=False),
    sa.Column('position', sa.SmallInteger(), nullable=False),
    sa.Column('question_id', sa.UUID(), nullable=False),
    sa.CheckConstraint('position >= 1', name=op.f('ck_test_form_item_position_positive')),
    sa.ForeignKeyConstraint(['form_id'], ['test_form.id'], name=op.f('fk_test_form_item_form_id_test_form'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['question_id'], ['question.id'], name=op.f('fk_test_form_item_question_id_question'), ondelete='NO ACTION'),
    sa.PrimaryKeyConstraint('form_id', 'position', name=op.f('pk_test_form_item')),
    sa.UniqueConstraint('form_id', 'question_id', name='uq_test_form_item_question')
    )
    op.create_index(op.f('ix_test_form_item_question_id'), 'test_form_item', ['question_id'], unique=False)
    op.create_table('attempt',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('learner_id', sa.UUID(), nullable=False),
    sa.Column('question_id', sa.UUID(), nullable=False),
    sa.Column('quiz_id', sa.UUID(), nullable=True),
    sa.Column('level', sa.Enum('basic', 'intermediate', 'advanced', name='difficulty_level'), nullable=False),
    sa.Column('selected_option', sa.SmallInteger(), nullable=True),
    sa.Column('answer_text', sa.Text(), nullable=True),
    sa.Column('is_correct', sa.Boolean(), nullable=False),
    sa.Column('evaluated_by', sa.Enum('auto', 'llm', name='evaluation_method'), nullable=False),
    sa.Column('feedback', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(selected_option IS NULL) = (evaluated_by = 'llm')", name=op.f('ck_attempt_evaluation_matches_form')),
    sa.CheckConstraint('answer_text IS NULL OR length(answer_text) <= 4000', name=op.f('ck_attempt_answer_length')),
    sa.CheckConstraint('num_nonnulls(selected_option, answer_text) = 1', name=op.f('ck_attempt_one_answer_form')),
    sa.ForeignKeyConstraint(['learner_id'], ['learner.id'], name=op.f('fk_attempt_learner_id_learner'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['question_id', 'selected_option'], ['question_option.question_id', 'question_option.position'], name='fk_attempt_selected_option', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['question_id'], ['question.id'], name=op.f('fk_attempt_question_id_question'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['quiz_id'], ['quiz.id'], name=op.f('fk_attempt_quiz_id_quiz'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_attempt'))
    )
    op.create_index('ix_attempt_learner_created', 'attempt', ['learner_id', 'created_at'], unique=False)
    op.create_index('ix_attempt_question_option', 'attempt', ['question_id', 'selected_option'], unique=False)
    op.create_index(op.f('ix_attempt_quiz_id'), 'attempt', ['quiz_id'], unique=False)
    op.create_table('message_source',
    sa.Column('message_id', sa.BigInteger(), nullable=False),
    sa.Column('chunk_id', sa.BigInteger(), nullable=False),
    sa.Column('rank', sa.SmallInteger(), nullable=False),
    sa.Column('similarity', sa.Float(), nullable=False),
    sa.CheckConstraint('rank BETWEEN 1 AND 20', name=op.f('ck_message_source_rank_range')),
    sa.CheckConstraint('similarity BETWEEN -1 AND 1', name=op.f('ck_message_source_similarity_range')),
    sa.ForeignKeyConstraint(['chunk_id'], ['chunk.id'], name=op.f('fk_message_source_chunk_id_chunk'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['message_id'], ['message.id'], name=op.f('fk_message_source_message_id_message'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('message_id', 'chunk_id', name=op.f('pk_message_source'))
    )
    op.create_index(op.f('ix_message_source_chunk_id'), 'message_source', ['chunk_id'], unique=False)
    op.create_table('adaptation_event',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('learner_id', sa.UUID(), nullable=False),
    sa.Column('section_id', sa.UUID(), nullable=False),
    sa.Column('attempt_id', sa.BigInteger(), nullable=True),
    sa.Column('quiz_id', sa.UUID(), nullable=True),
    sa.Column('rule', sa.String(length=40), nullable=False),
    sa.Column('from_level', sa.Enum('basic', 'intermediate', 'advanced', name='difficulty_level'), nullable=True),
    sa.Column('to_level', sa.Enum('basic', 'intermediate', 'advanced', name='difficulty_level'), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['attempt_id'], ['attempt.id'], name=op.f('fk_adaptation_event_attempt_id_attempt'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['learner_id'], ['learner.id'], name=op.f('fk_adaptation_event_learner_id_learner'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['quiz_id'], ['quiz.id'], name=op.f('fk_adaptation_event_quiz_id_quiz'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['rule'], ['adaptation_rule.code'], name=op.f('fk_adaptation_event_rule_adaptation_rule'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['section_id'], ['section.id'], name=op.f('fk_adaptation_event_section_id_section'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_adaptation_event'))
    )
    op.create_index(op.f('ix_adaptation_event_attempt_id'), 'adaptation_event', ['attempt_id'], unique=False)
    op.create_index('ix_adaptation_event_learner_section', 'adaptation_event', ['learner_id', 'section_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_adaptation_event_quiz_id'), 'adaptation_event', ['quiz_id'], unique=False)
    op.create_index(op.f('ix_adaptation_event_rule'), 'adaptation_event', ['rule'], unique=False)
    op.create_index(op.f('ix_adaptation_event_section_id'), 'adaptation_event', ['section_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_adaptation_event_section_id'), table_name='adaptation_event')
    op.drop_index(op.f('ix_adaptation_event_rule'), table_name='adaptation_event')
    op.drop_index(op.f('ix_adaptation_event_quiz_id'), table_name='adaptation_event')
    op.drop_index('ix_adaptation_event_learner_section', table_name='adaptation_event')
    op.drop_index(op.f('ix_adaptation_event_attempt_id'), table_name='adaptation_event')
    op.drop_table('adaptation_event')
    op.drop_index(op.f('ix_message_source_chunk_id'), table_name='message_source')
    op.drop_table('message_source')
    op.drop_index(op.f('ix_attempt_quiz_id'), table_name='attempt')
    op.drop_index('ix_attempt_question_option', table_name='attempt')
    op.drop_index('ix_attempt_learner_created', table_name='attempt')
    op.drop_table('attempt')
    op.drop_index(op.f('ix_test_form_item_question_id'), table_name='test_form_item')
    op.drop_table('test_form_item')
    op.drop_index(op.f('ix_quiz_item_question_id'), table_name='quiz_item')
    op.drop_table('quiz_item')
    op.drop_index('uq_question_option_one_correct', table_name='question_option', postgresql_where=sa.text('is_correct'))
    op.drop_table('question_option')
    op.drop_index('ix_message_session_id', table_name='message')
    op.drop_table('message')
    op.drop_index(op.f('ix_topic_state_section_id'), table_name='topic_state')
    op.drop_index('ix_topic_state_learner_gaps', table_name='topic_state', postgresql_where=sa.text("status = 'gap'"))
    op.drop_index('ix_topic_state_due_reviews', table_name='topic_state', postgresql_where=sa.text('next_review_at IS NOT NULL'))
    op.drop_table('topic_state')
    op.drop_index('uq_quiz_one_open_check', table_name='quiz', postgresql_where=sa.text("kind = 'check' AND status = 'in_progress'"))
    op.drop_index(op.f('ix_quiz_section_id'), table_name='quiz')
    op.drop_index('ix_quiz_learner_started', table_name='quiz')
    op.drop_table('quiz')
    op.drop_index('ix_question_section_level', table_name='question')
    op.drop_table('question')
    op.drop_index('ix_chunk_embedding_hnsw', table_name='chunk', postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.drop_index('ix_chunk_content_fts', table_name='chunk', postgresql_using='gin')
    op.drop_table('chunk')
    op.drop_index(op.f('ix_chat_session_section_id'), table_name='chat_session')
    op.drop_index('ix_chat_session_learner_started', table_name='chat_session')
    op.drop_table('chat_session')
    op.drop_index(op.f('ix_section_parent_id'), table_name='section')
    op.drop_table('section')
    op.drop_table('test_form')
    op.drop_index(op.f('ix_document_course_id'), table_name='document')
    op.drop_table('document')
    op.drop_table('learner')
    op.drop_index(op.f('ix_course_owner_account_id'), table_name='course')
    op.drop_table('course')
    op.drop_index(op.f('ix_account_consent_version'), table_name='account')
    op.drop_table('account')
    op.drop_table('privacy_notice')
    op.drop_table('adaptation_rule')
    for enum_type in ("account_role", "experiment_mode", "difficulty_level", "course_visibility",
                      "document_status", "question_kind", "question_source", "quiz_kind", "quiz_status",
                      "topic_status", "check_end_reason", "evaluation_method", "chat_mode", "message_role",
                      "test_kind"):
        op.execute(f"DROP TYPE IF EXISTS {enum_type}")
