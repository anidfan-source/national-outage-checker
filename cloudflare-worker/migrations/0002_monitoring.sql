CREATE TABLE IF NOT EXISTS subscription_status (
  topic TEXT PRIMARY KEY,
  confirmed_at TEXT NOT NULL,
  last_confirmation_message_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS topic_activity (
  topic TEXT PRIMARY KEY,
  last_event_at TEXT,
  last_received_at TEXT NOT NULL,
  event_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS messages_retention_idx ON messages(received_at);
