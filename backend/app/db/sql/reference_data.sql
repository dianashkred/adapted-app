INSERT INTO privacy_notice (version, published_on, summary) VALUES
  ('1.0', DATE '2026-11-01', 'First Privacy Notice: data processed for learning and for the anonymised diploma experiment (GDPR Art. 6(1)(a)).')
ON CONFLICT (version) DO UPDATE SET published_on = EXCLUDED.published_on, summary = EXCLUDED.summary;

INSERT INTO adaptation_rule (code, description) VALUES
  ('check_started',      'A topic knowledge check started; the first question is Intermediate.'),
  ('level_up',           'Correct answer: the next question is one level harder (max Advanced). US-12.'),
  ('level_down',         'Incorrect answer: the error is explained and the next question is one level easier (min Basic). US-12.'),
  ('basic_chapter_link', 'Two incorrect answers in a row: the basic chapter of the topic is linked and the check ends. US-12.'),
  ('topic_mastered',     'Check ended with status Mastered (US-11 rule applied to the answers of the check).'),
  ('topic_gap',          'Check ended with status Gap; the topic is offered for review after one day (US-20).')
ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description;
