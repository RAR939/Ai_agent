-- Схема базы data/helper.db (docs/contracts.md, раздел 5) + индексы.
-- Время хранится строками ISO 8601 с поясом +03:00.
CREATE TABLE IF NOT EXISTS deadlines(
  id INTEGER PRIMARY KEY,
  discipline TEXT NOT NULL,
  kind TEXT NOT NULL,
  task TEXT NOT NULL,
  due_at TEXT,              -- ISO, NULL если срок размытый
  due_text TEXT NOT NULL,
  fuzzy INTEGER DEFAULT 0,
  status TEXT DEFAULT 'active',
  source_msg TEXT NOT NULL,
  confidence REAL,
  updated_at TEXT);

CREATE TABLE IF NOT EXISTS deadline_history(
  id INTEGER PRIMARY KEY,
  deadline_id INTEGER REFERENCES deadlines(id),
  old_due TEXT, new_due TEXT,
  source_msg TEXT, changed_at TEXT);

CREATE TABLE IF NOT EXISTS pending(
  id INTEGER PRIMARY KEY,
  candidate_json TEXT NOT NULL,   -- Deadline как JSON (вместе с attachments)
  matched_id INTEGER,             -- на что похоже, если нашли
  reason TEXT,                    -- low_confidence | ambiguous_match | no_match_for_move
  source_text TEXT,
  created_at TEXT);

CREATE TABLE IF NOT EXISTS lessons(
  id INTEGER PRIMARY KEY,
  discipline TEXT, lesson_type TEXT,
  start TEXT, end TEXT, teacher TEXT, room TEXT);

CREATE TABLE IF NOT EXISTS processed_msgs(
  msg_id TEXT PRIMARY KEY,
  processed_at TEXT,
  had_deadline INTEGER);

CREATE TABLE IF NOT EXISTS files(
  id TEXT PRIMARY KEY,
  msg_id TEXT NOT NULL,
  name TEXT NOT NULL, ext TEXT, size_bytes INTEGER,
  path TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS deadline_files(
  deadline_id INTEGER REFERENCES deadlines(id),
  file_id TEXT REFERENCES files(id),
  bind TEXT,                    -- same_message | same_author_near | reply_context
  linked_at TEXT,
  PRIMARY KEY(deadline_id, file_id));

CREATE TABLE IF NOT EXISTS labels(
  msg_id TEXT PRIMARY KEY,
  model_json TEXT, human_json TEXT,
  prompt_version TEXT, model_name TEXT);

-- Внутренняя таблица роли 4 (задача 4.10): отправленные напоминания.
-- Ключ включает срок: после переноса напоминание уйдёт заново.
CREATE TABLE IF NOT EXISTS reminders(
  deadline_id INTEGER REFERENCES deadlines(id),
  due_at TEXT,
  sent_at TEXT,
  PRIMARY KEY(deadline_id, due_at));

CREATE INDEX IF NOT EXISTS idx_deadlines_disc_task ON deadlines(discipline, task);
CREATE INDEX IF NOT EXISTS idx_deadlines_due ON deadlines(due_at);
CREATE INDEX IF NOT EXISTS idx_history_deadline ON deadline_history(deadline_id);
CREATE INDEX IF NOT EXISTS idx_lessons_start ON lessons(start);
