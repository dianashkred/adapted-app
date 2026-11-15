# Data dictionary

Generated from the ORM models by `python -m scripts.generate_data_dictionary`. Layers: one transactional (OLTP) layer in schema `public`; pseudonymised read-only views in schema `analytics`.

## Reference data

### `privacy_notice`

Versions of the Privacy Notice; every consent refers to one version.

| Column | Type | Null | Key | Description |
| --- | --- | --- | --- | --- |
| `version` | varchar(20) | no | PK | Version 'major.minor'. |
| `published_on` | date | no |  | Publication date. |
| `summary` | text | no |  | Short content of the notice. |

**Data-quality rules (enforced by the database):**

- CHECK `ck_privacy_notice_version_format`: `version ~ '^[0-9]+\.[0-9]+$'`

### `adaptation_rule`

Codes of the learner-model and knowledge-check rules used in adaptation_event.

| Column | Type | Null | Key | Description |
| --- | --- | --- | --- | --- |
| `code` | varchar(40) | no | PK | Rule code (snake_case). |
| `description` | text | no |  | What the rule does and which user story it implements. |

**Data-quality rules (enforced by the database):**

- CHECK `ck_adaptation_rule_code_format`: `code ~ '^[a-z_]+$'`

## Identity

### `account`

User account. The ONLY table with personal data (e-mail, encrypted). No passwords.

| Column | Type | Null | Key | Description |
| --- | --- | --- | --- | --- |
| `id` | uuid default `gen_random_uuid()` | no | PK | Random UUID. |
| `auth_subject` | varchar(64) | no | UQ | User id ('sub') of Supabase Auth; the password stays with the identity provider (bcrypt). |
| `email_hash` | varchar(64) | no | UQ | HMAC-SHA256 of the normalised e-mail (64 hex), for look-ups and uniqueness. |
| `email_encrypted` | blob | no |  | E-mail encrypted with Fernet (AES-128 + HMAC); key outside the database. |
| `role` | enum `account_role` (student, admin) default `student` | no |  | student or admin. |
| `consent_version` | varchar(20) | no | FK → privacy_notice.version (RESTRICT) | Accepted Privacy Notice version. |
| `consent_given_at` | timestamptz | no |  | Time of consent (GDPR Art. 7(1)); not in the future. |
| `last_login_at` | timestamptz | yes |  | Last sign-in. |
| `created_at` | timestamptz default `now()` | no |  | Creation time. |

**Data-quality rules (enforced by the database):**

- CHECK `ck_account_consent_not_in_future`: `consent_given_at <= now() + interval '1 minute'`
- CHECK `ck_account_email_hash_hex`: `email_hash ~ '^[0-9a-f]{64}$'`

**Indexes:** `ix_account_consent_version`

### `learner`

Pseudonymous learner (1:1 with account) used by all learning data and exports; preferences; simulated profiles (no account) for KPI K2.

| Column | Type | Null | Key | Description |
| --- | --- | --- | --- | --- |
| `id` | uuid default `gen_random_uuid()` | no | PK | Pseudonymous id used everywhere instead of the account. |
| `account_id` | uuid | yes | FK → account.id (CASCADE), UQ | Owning account (unique, 1:1); NULL exactly for simulated learners. |
| `is_participant` | boolean default `false` | no |  | Registered with the experiment code (US-15). |
| `experiment_mode` | enum `experiment_mode` (plain_rag, adaptive) | yes |  | plain_rag (A) / adaptive (B); only for participants. |
| `mode_assigned_at` | timestamptz | yes |  | Set together with experiment_mode. |
| `starting_level` | enum `difficulty_level` (basic, intermediate, advanced) default `intermediate` | no |  | Default level of a new topic. |
| `is_simulated` | boolean default `false` | no |  | Simulated profile (US-18): no account; excluded from real-participant results, flagged in analytics. |
| `ui_theme` | enum `ui_theme` (system, light, dark) default `system` | no |  | Preferred colour theme: system / light / dark (default system). |
| `revision_reminders` | boolean default `true` | no |  | Offer revision quizzes (default true); the learner can switch it off. |
| `last_seen_at` | timestamptz | yes |  | Last visit; used for the absence rule of the revision offer. |
| `created_at` | timestamptz default `now()` | no |  | Creation time. |

**Data-quality rules (enforced by the database):**

- CHECK `ck_learner_mode_only_for_participants`: `experiment_mode IS NULL OR is_participant`
- CHECK `ck_learner_mode_and_time_together`: `(experiment_mode IS NULL) = (mode_assigned_at IS NULL)`
- CHECK `ck_learner_account_iff_real`: `(account_id IS NOT NULL) = (NOT is_simulated)`

## Course materials

### `course`

A course: private (owner only) or shared (evaluation corpus).

| Column | Type | Null | Key | Description |
| --- | --- | --- | --- | --- |
| `id` | uuid default `gen_random_uuid()` | no | PK | UUID. |
| `owner_account_id` | uuid | yes | FK → account.id (CASCADE) | Owner; NULL only for shared courses. |
| `title` | varchar(200) | no |  | Title, not blank. |
| `language` | varchar(10) default `'en'` | no |  | Language code of the materials. |
| `visibility` | enum `course_visibility` (private, shared) default `private` | no |  | private or shared. |
| `created_at` | timestamptz default `now()` | no |  | Creation time. |

**Data-quality rules (enforced by the database):**

- CHECK `ck_course_title_not_blank`: `length(btrim(title)) > 0`
- CHECK `ck_course_private_course_has_owner`: `owner_account_id IS NOT NULL OR visibility = 'shared'`

**Indexes:** `ix_course_owner_account_id`

### `document`

Uploaded file of a course, path of the original in private storage, processing status.

| Column | Type | Null | Key | Description |
| --- | --- | --- | --- | --- |
| `id` | uuid default `gen_random_uuid()` | no | PK | UUID. |
| `course_id` | uuid | no | FK → course.id (CASCADE) | Course. |
| `file_name` | varchar(255) | no |  | Original file name. |
| `mime_type` | varchar(100) | no |  | PDF, DOCX, TXT or Markdown only. |
| `size_bytes` | bigint | no |  | 1 byte – 50 MB. |
| `sha256` | varchar(64) | no |  | Hash of the file; unique per course (no double indexing). |
| `storage_path` | varchar(500) | yes | UQ | Path of the original in private storage (US-04); required when ready; unique. |
| `status` | enum `document_status` (processing, ready, failed) default `processing` | no |  | processing / ready / failed. |
| `error_message` | text | yes |  | Required when failed (e.g. no text layer). |
| `page_count` | integer | yes |  | Pages (> 0) where the format has pages. |
| `uploaded_at` | timestamptz default `now()` | no |  | Upload time. |
| `processed_at` | timestamptz | yes |  | Required when ready. |

**Data-quality rules (enforced by the database):**

- UNIQUE (course_id, sha256)
- CHECK `ck_document_ready_is_complete`: `status <> 'ready' OR (processed_at IS NOT NULL AND storage_path IS NOT NULL)`
- CHECK `ck_document_allowed_mime`: `mime_type IN ('application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'text/plain', 'text/markdown')`
- CHECK `ck_document_page_count_positive`: `page_count IS NULL OR page_count > 0`
- CHECK `ck_document_sha256_hex`: `sha256 ~ '^[0-9a-f]{64}$'`
- CHECK `ck_document_size_limit`: `size_bytes > 0 AND size_bytes <= 52428800`
- CHECK `ck_document_failed_has_reason`: `status <> 'failed' OR error_message IS NOT NULL`

**Indexes:** `ix_document_course_id`

### `section`

Heading tree of a document; level-1 sections are the topics of the learner model.

| Column | Type | Null | Key | Description |
| --- | --- | --- | --- | --- |
| `id` | uuid default `gen_random_uuid()` | no | PK | UUID. |
| `document_id` | uuid | no | FK → document.id (CASCADE) | Document. |
| `parent_id` | uuid | yes | FK → section.id (CASCADE) | Parent section; NULL only for level 1 (topics). |
| `level` | smallint | no |  | Heading level 1–6. |
| `position` | integer | no |  | Order inside the document (unique). |
| `title` | varchar(300) | no |  | Heading text. |
| `page_start` | integer | yes |  | First page. |
| `page_end` | integer | yes |  | Last page (>= page_start). |

**Data-quality rules (enforced by the database):**

- UNIQUE (document_id, position)
- CHECK `ck_section_level_range`: `level BETWEEN 1 AND 6`
- CHECK `ck_section_page_order`: `page_end IS NULL OR page_start IS NULL OR page_end >= page_start`
- CHECK `ck_section_only_topics_have_no_parent`: `(level = 1) = (parent_id IS NULL)`
- CHECK `ck_section_position_non_negative`: `position >= 0`

**Indexes:** `ix_section_parent_id`

### `chunk`

Text passage of a section with its 384-dim embedding for retrieval (RAG).

| Column | Type | Null | Key | Description |
| --- | --- | --- | --- | --- |
| `id` | bigint | no | PK | Identity. |
| `section_id` | uuid | no | FK → section.id (CASCADE) | Section. |
| `position` | integer | no |  | Order inside the section (unique). |
| `content` | text | no |  | Text, not empty. |
| `token_count` | integer | no |  | 1–2000 tokens (target ≈ 350). |
| `page` | integer | yes |  | Page of the passage. |
| `embedding` | vector(384) | no |  | vector(384), BAAI/bge-small-en-v1.5, cosine; HNSW index. |
| `created_at` | timestamptz default `now()` | no |  | Creation time. |

**Data-quality rules (enforced by the database):**

- UNIQUE (section_id, position)
- CHECK `ck_chunk_token_count_range`: `token_count BETWEEN 1 AND 2000`
- CHECK `ck_chunk_content_not_empty`: `length(content) > 0`

**Indexes:** `ix_chunk_content_fts`, `ix_chunk_embedding_hnsw`

## Assessment

### `question`

Check / review / test question about a section, generated or curated, with reference answer.

| Column | Type | Null | Key | Description |
| --- | --- | --- | --- | --- |
| `id` | uuid default `gen_random_uuid()` | no | PK | UUID. |
| `section_id` | uuid | no | FK → section.id (CASCADE) | Section the question is about. |
| `level` | enum `difficulty_level` (basic, intermediate, advanced) | no |  | basic / intermediate / advanced. |
| `kind` | enum `question_kind` (multiple_choice, free_text) | no |  | multiple_choice or free_text. |
| `source` | enum `question_source` (generated, curated) | no |  | generated (LLM) or curated (admin). |
| `prompt` | text | no |  | Question text, not blank. |
| `reference_answer` | text | no |  | Answer used for evaluation, not blank. |
| `created_at` | timestamptz default `now()` | no |  | Creation time. |

**Data-quality rules (enforced by the database):**

- CHECK `ck_question_reference_not_blank`: `length(btrim(reference_answer)) > 0`
- CHECK `ck_question_prompt_not_blank`: `length(btrim(prompt)) > 0`

**Indexes:** `ix_question_section_level`

### `question_option`

Option of a multiple-choice question; exactly one is correct.

| Column | Type | Null | Key | Description |
| --- | --- | --- | --- | --- |
| `question_id` | uuid | no | PK, FK → question.id (CASCADE) | Question. |
| `position` | smallint | no | PK | 1–6. |
| `option_text` | text | no |  | Text, not blank. |
| `is_correct` | boolean default `false` | no |  | Exactly one true per question. |

**Data-quality rules (enforced by the database):**

- CHECK `ck_question_option_text_not_blank`: `length(btrim(option_text)) > 0`
- CHECK `ck_question_option_position_range`: `position BETWEEN 1 AND 6`

**Indexes:** `uq_question_option_one_correct`

### `quiz`

Questions given to a learner: knowledge check (max 6), review, topic quiz (<= 30), revision quiz (10-20), pre-test or post-test; result of a check.

| Column | Type | Null | Key | Description |
| --- | --- | --- | --- | --- |
| `id` | uuid default `gen_random_uuid()` | no | PK | UUID. |
| `learner_id` | uuid | no | FK → learner.id (CASCADE) | Learner. |
| `section_id` | uuid | yes | FK → section.id (CASCADE) | Topic of a check or topic quiz (required for both). |
| `kind` | enum `quiz_kind` (check, review, pre_test, post_test, topic_quiz, revision) | no |  | check / review / pre_test / post_test / topic_quiz / revision. |
| `status` | enum `quiz_status` (in_progress, completed, abandoned) default `in_progress` | no |  | in_progress / completed / abandoned. |
| `max_questions` | smallint default `6` | no |  | 1–30; a check has at most 6; a revision quiz 10–20. Topic/revision quizzes close automatically at the limit. |
| `outcome` | enum `topic_status` (not_checked, gap, mastered) | yes |  | Result of a check: not_checked / gap / mastered (US-11 rule on the answers of the check). |
| `end_reason` | enum `check_end_reason` (success_sequence, two_consecutive_errors, question_limit, stopped_by_learner) | yes |  | success_sequence / two_consecutive_errors / question_limit / stopped_by_learner. |
| `started_at` | timestamptz default `now()` | no |  | Start. |
| `ended_at` | timestamptz | yes |  | Set exactly when the quiz is closed. |

**Data-quality rules (enforced by the database):**

- CHECK `ck_quiz_completed_check_has_result`: `kind <> 'check' OR status <> 'completed' OR (outcome IS NOT NULL AND end_reason IS NOT NULL)`
- CHECK `ck_quiz_end_reason_only_for_checks`: `kind = 'check' OR end_reason IS NULL`
- CHECK `ck_quiz_max_questions_range`: `max_questions BETWEEN 1 AND 30`
- CHECK `ck_quiz_topic_quiz_is_per_topic`: `kind <> 'topic_quiz' OR section_id IS NOT NULL`
- CHECK `ck_quiz_ended_iff_closed`: `(status = 'in_progress') = (ended_at IS NULL)`
- CHECK `ck_quiz_time_order`: `ended_at IS NULL OR ended_at >= started_at`
- CHECK `ck_quiz_check_is_per_topic`: `kind <> 'check' OR (section_id IS NOT NULL AND max_questions <= 6)`
- CHECK `ck_quiz_revision_size`: `kind <> 'revision' OR max_questions BETWEEN 10 AND 20`

**Indexes:** `ix_quiz_learner_started`, `uq_quiz_one_open_check`, `ix_quiz_section_id`

### `quiz_item`

Question asked inside a quiz, in order (N:M between quiz and question).

| Column | Type | Null | Key | Description |
| --- | --- | --- | --- | --- |
| `quiz_id` | uuid | no | PK, FK → quiz.id (CASCADE) | Quiz. |
| `position` | smallint | no | PK | Order (>= 1). |
| `question_id` | uuid | no | FK → question.id (CASCADE) | Question (unique in the quiz). |

**Data-quality rules (enforced by the database):**

- UNIQUE (quiz_id, question_id)
- CHECK `ck_quiz_item_position_positive`: `position >= 1`

**Indexes:** `ix_quiz_item_question_id`

### `attempt`

One answer with its evaluation. Immutable. Inserting it fires the learner-model trigger.

| Column | Type | Null | Key | Description |
| --- | --- | --- | --- | --- |
| `id` | bigint | no | PK | Identity. |
| `learner_id` | uuid | no | FK → learner.id (CASCADE) | Learner (must be the quiz's learner). |
| `question_id` | uuid | no | FK → question.id (CASCADE), FK → question_option.question_id (CASCADE) | Question. |
| `quiz_id` | uuid | yes | FK → quiz.id (CASCADE) | Quiz, if any. |
| `level` | enum `difficulty_level` (basic, intermediate, advanced) | no |  | Level at which the question was asked. |
| `selected_option` | smallint | yes | FK → question_option.position (CASCADE) | Chosen option (multiple choice). |
| `answer_text` | text | yes |  | Free-text answer (max 4000 chars). |
| `is_correct` | boolean | no |  | Evaluation result. |
| `evaluated_by` | enum `evaluation_method` (auto, llm) | no |  | auto (multiple choice) or llm (free text). |
| `feedback` | text | yes |  | Explanation shown to the learner. |
| `confidence` | enum `answer_confidence` (sure, not_sure, guessing) | yes |  | sure / not_sure / guessing; required in check, review, topic and revision quizzes, NULL in pre-/post-tests. |
| `created_at` | timestamptz default `now()` | no |  | Time of the answer. |

**Data-quality rules (enforced by the database):**

- CHECK `ck_attempt_answer_length`: `answer_text IS NULL OR length(answer_text) <= 4000`
- CHECK `ck_attempt_one_answer_form`: `num_nonnulls(selected_option, answer_text) = 1`
- CHECK `ck_attempt_evaluation_matches_form`: `(selected_option IS NULL) = (evaluated_by = 'llm')`

**Indexes:** `ix_attempt_learner_created`, `ix_attempt_question_option`, `ix_attempt_quiz_id`, `uq_attempt_quiz_question`

## Learner model

### `topic_state`

Status, level and counters of one learner for one topic (documented denormalisation).

| Column | Type | Null | Key | Description |
| --- | --- | --- | --- | --- |
| `learner_id` | uuid | no | PK, FK → learner.id (CASCADE) | Learner. |
| `section_id` | uuid | no | PK, FK → section.id (CASCADE) | Topic (level-1 section). |
| `status` | enum `topic_status` (not_checked, gap, mastered) default `not_checked` | no |  | not_checked / gap / mastered. |
| `current_level` | enum `difficulty_level` (basic, intermediate, advanced) default `intermediate` | no |  | Level of the next question. |
| `attempts_count` | integer default `0` | no |  | Answers on the topic (maintained by trigger). |
| `correct_count` | integer default `0` | no |  | Correct answers (<= attempts_count). |
| `consecutive_errors` | smallint default `0` | no |  | Wrong answers in a row. |
| `last_attempt_at` | timestamptz | yes |  | Last answer. |
| `next_review_at` | timestamptz | yes |  | When the topic is offered for review (US-20). |
| `updated_at` | timestamptz default `now()` | no |  | Maintained by trigger. |

**Data-quality rules (enforced by the database):**

- CHECK `ck_topic_state_consecutive_errors_non_negative`: `consecutive_errors >= 0`
- CHECK `ck_topic_state_counters_consistent`: `attempts_count >= 0 AND correct_count >= 0 AND correct_count <= attempts_count`

**Indexes:** `ix_topic_state_due_reviews`, `ix_topic_state_section_id`, `ix_topic_state_learner_gaps`

### `adaptation_event`

Log of every decision of the tutor (level change, basic chapter, check result).

| Column | Type | Null | Key | Description |
| --- | --- | --- | --- | --- |
| `id` | bigint | no | PK | Identity. |
| `learner_id` | uuid | no | FK → learner.id (CASCADE) | Learner. |
| `section_id` | uuid | no | FK → section.id (CASCADE) | Topic. |
| `attempt_id` | bigint | yes | FK → attempt.id (CASCADE) | Answer that caused it. |
| `quiz_id` | uuid | yes | FK → quiz.id (CASCADE) | Check it belongs to. |
| `rule` | varchar(40) | no | FK → adaptation_rule.code (RESTRICT) | Rule code (adaptation_rule). |
| `from_level` | enum `difficulty_level` (basic, intermediate, advanced) | yes |  | Level before. |
| `to_level` | enum `difficulty_level` (basic, intermediate, advanced) | yes |  | Level after. |
| `created_at` | timestamptz default `now()` | no |  | Decision time. |

**Indexes:** `ix_adaptation_event_attempt_id`, `ix_adaptation_event_rule`, `ix_adaptation_event_section_id`, `ix_adaptation_event_quiz_id`, `ix_adaptation_event_learner_section`

### `review_item`

The learner's review list: questions answered incorrectly or with low confidence (not_sure / guessing); maintained by trigger (decision 0002).

| Column | Type | Null | Key | Description |
| --- | --- | --- | --- | --- |
| `learner_id` | uuid | no | PK, FK → learner.id (CASCADE) | Learner (not mode A participants). |
| `question_id` | uuid | no | PK, FK → question.id (CASCADE) | Question to review. |
| `reason` | enum `review_reason` (incorrect, unsure) | no |  | incorrect, or unsure (correct but not_sure / guessing). |
| `first_attempt_id` | bigint | yes | FK → attempt.id (SET NULL) | Answer that first put the question on the list (SET NULL if its quiz is deleted). |
| `last_attempt_id` | bigint | yes | FK → attempt.id (SET NULL) | Answer that last added or resolved it (SET NULL if its quiz is deleted). |
| `times_added` | smallint default `1` | no |  | How many answers put or kept the question on the list (>= 1). |
| `added_at` | timestamptz default `now()` | no |  | First time on the list. |
| `due_at` | timestamptz | no |  | One day after the last incorrect / unsure answer. |
| `resolved_at` | timestamptz | yes |  | Set by a later correct answer with confidence sure; NULL = open. |

**Data-quality rules (enforced by the database):**

- CHECK `ck_review_item_resolved_after_added`: `resolved_at IS NULL OR resolved_at >= added_at`
- CHECK `ck_review_item_times_added_positive`: `times_added >= 1`
- CHECK `ck_review_item_due_after_added`: `due_at >= added_at`

**Indexes:** `ix_review_item_question_id`, `ix_review_item_first_attempt_id`, `ix_review_item_last_attempt_id`, `ix_review_item_open_due`

## Chat

### `chat_session`

A free-question chat or a guided lesson of a learner about a topic.

| Column | Type | Null | Key | Description |
| --- | --- | --- | --- | --- |
| `id` | uuid default `gen_random_uuid()` | no | PK | UUID. |
| `learner_id` | uuid | no | FK → learner.id (CASCADE) | Learner. |
| `section_id` | uuid | no | FK → section.id (CASCADE) | Topic. |
| `mode` | enum `chat_mode` (guided, free_question) | no |  | guided or free_question. |
| `current_step` | smallint default `0` | no |  | Shown part of a guided lesson. |
| `total_steps` | smallint | yes |  | Parts of a guided lesson (only guided). |
| `started_at` | timestamptz default `now()` | no |  | Start. |
| `ended_at` | timestamptz | yes |  | End. |

**Data-quality rules (enforced by the database):**

- CHECK `ck_chat_session_time_order`: `ended_at IS NULL OR ended_at >= started_at`
- CHECK `ck_chat_session_steps_only_for_guided`: `(mode = 'guided') = (total_steps IS NOT NULL)`
- CHECK `ck_chat_session_step_range`: `current_step >= 0 AND (total_steps IS NULL OR current_step <= total_steps)`

**Indexes:** `ix_chat_session_section_id`, `ix_chat_session_learner_started`

### `message`

Question of the learner or answer of the tutor with LLM metrics.

| Column | Type | Null | Key | Description |
| --- | --- | --- | --- | --- |
| `id` | bigint | no | PK | Identity, also the order. |
| `session_id` | uuid | no | FK → chat_session.id (CASCADE) | Chat. |
| `role` | enum `message_role` (user, assistant) | no |  | user or assistant. |
| `content` | text | no |  | Text; user input <= 1000 chars (US-06). |
| `model` | varchar(100) | yes |  | LLM of an answer. |
| `latency_ms` | integer | yes |  | Time to the full answer (NFR-02). |
| `prompt_tokens` | integer | yes |  | Tokens sent. |
| `completion_tokens` | integer | yes |  | Tokens received. |
| `max_similarity` | float | yes |  | Best retrieval similarity (K1). |
| `is_refusal` | boolean default `false` | no |  | Honest refusal (US-07). |
| `created_at` | timestamptz default `now()` | no |  | Creation time. |

**Data-quality rules (enforced by the database):**

- CHECK `ck_message_similarity_range`: `max_similarity IS NULL OR max_similarity BETWEEN -1 AND 1`
- CHECK `ck_message_question_length`: `role = 'assistant' OR length(content) <= 1000`
- CHECK `ck_message_content_not_empty`: `length(content) > 0`
- CHECK `ck_message_llm_fields_only_for_answers`: `role = 'assistant' OR (model IS NULL AND latency_ms IS NULL AND NOT is_refusal)`
- CHECK `ck_message_latency_non_negative`: `latency_ms IS NULL OR latency_ms >= 0`

**Indexes:** `ix_message_session_id`

### `message_source`

Chunks retrieved for an answer and shown as its sources.

| Column | Type | Null | Key | Description |
| --- | --- | --- | --- | --- |
| `message_id` | bigint | no | PK, FK → message.id (CASCADE) | Answer. |
| `chunk_id` | bigint | no | PK, FK → chunk.id (CASCADE) | Chunk shown as source. |
| `rank` | smallint | no |  | 1 = most similar (1–20). |
| `similarity` | float | no |  | Cosine similarity −1…1. |

**Data-quality rules (enforced by the database):**

- CHECK `ck_message_source_rank_range`: `rank BETWEEN 1 AND 20`
- CHECK `ck_message_source_similarity_range`: `similarity BETWEEN -1 AND 1`

**Indexes:** `ix_message_source_chunk_id`

## Experiment

### `test_form`

Fixed pre- or post-test of a course, identical for modes A and B.

| Column | Type | Null | Key | Description |
| --- | --- | --- | --- | --- |
| `id` | uuid default `gen_random_uuid()` | no | PK | UUID. |
| `course_id` | uuid | no | FK → course.id (CASCADE) | Course. |
| `kind` | enum `test_kind` (pre_test, post_test) | no |  | pre_test or post_test (one each per course). |
| `title` | varchar(200) | no |  | Title. |
| `created_at` | timestamptz default `now()` | no |  | Creation time. |

**Data-quality rules (enforced by the database):**

- UNIQUE (course_id, kind)

### `test_form_item`

Question of a test form, in order.

| Column | Type | Null | Key | Description |
| --- | --- | --- | --- | --- |
| `form_id` | uuid | no | PK, FK → test_form.id (CASCADE) | Test form. |
| `position` | smallint | no | PK | Order. |
| `question_id` | uuid | no | FK → question.id (NO ACTION) | Curated question (unique in the form). |

**Data-quality rules (enforced by the database):**

- UNIQUE (form_id, question_id)
- CHECK `ck_test_form_item_position_positive`: `position >= 1`

**Indexes:** `ix_test_form_item_question_id`

### `simulated_gap`

Ground-truth gap topics of a simulated learner (US-18, KPI K2), compared with topic_state.status.

| Column | Type | Null | Key | Description |
| --- | --- | --- | --- | --- |
| `learner_id` | uuid | no | PK, FK → learner.id (CASCADE) | Simulated learner (is_simulated). |
| `section_id` | uuid | no | PK, FK → section.id (CASCADE) | Topic (level-1 section) that is a real gap of the profile. |

**Indexes:** `ix_simulated_gap_section_id`
