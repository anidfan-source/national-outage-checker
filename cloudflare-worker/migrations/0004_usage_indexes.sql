CREATE INDEX IF NOT EXISTS idx_messages_received_at
ON messages(received_at);

CREATE INDEX IF NOT EXISTS idx_messages_topic_received_at
ON messages(topic, received_at DESC);

