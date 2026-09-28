-- Keep only the latest Street Manager state for each object within a topic.
-- Existing history is compacted first so the unique index can be created safely.

DELETE FROM messages
WHERE object_reference IS NOT NULL
  AND rowid NOT IN (
    SELECT MAX(rowid)
    FROM messages
    WHERE object_reference IS NOT NULL
    GROUP BY topic, object_reference
  );

CREATE UNIQUE INDEX IF NOT EXISTS messages_topic_object_reference_uidx
ON messages(topic, object_reference)
WHERE object_reference IS NOT NULL;
