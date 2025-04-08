CREATE TABLE IF NOT EXISTS bot_config(
    id INTEGER PRIMARY KEY,
    `key` TEXT,
    `value` TEXT,
    UNIQUE(`key`)
);
CREATE INDEX IF NOT EXISTS bot_config_ix_key ON bot_config(`key`);
