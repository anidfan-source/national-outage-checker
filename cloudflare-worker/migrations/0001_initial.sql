CREATE TABLE IF NOT EXISTS messages (
  message_id TEXT PRIMARY KEY,
  received_at TEXT NOT NULL,
  event_time TEXT,
  event_type TEXT,
  object_reference TEXT,
  object_type TEXT,
  topic TEXT NOT NULL,
  payload TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS messages_received_at_idx ON messages(received_at DESC);
CREATE INDEX IF NOT EXISTS messages_topic_received_at_idx ON messages(topic, received_at DESC);
