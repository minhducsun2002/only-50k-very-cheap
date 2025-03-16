CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY,
    name TEXT,
    content TEXT,
    owner_id BIGINT,
    guild_id BIGINT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS tags_ix_name ON tags (name);
CREATE INDEX IF NOT EXISTS tags_ix_guild_id ON tags (guild_id);
CREATE INDEX IF NOT EXISTS tags_ix_name_lower ON tags (LOWER(name));
CREATE UNIQUE INDEX IF NOT EXISTS tags_uq_ix_name_lower_guild_id ON tags (LOWER(name), guild_id);

CREATE TABLE IF NOT EXISTS tag_lookup(
    id INTEGER PRIMARY KEY,
    name TEXT,
    tag_id INTEGER,
    owner_id BIGINT,
    guild_id BIGINT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS tag_lookup_ix_name ON tag_lookup (name);
CREATE INDEX IF NOT EXISTS tag_lookup_ix_guild_id ON tag_lookup (guild_id);
CREATE INDEX IF NOT EXISTS tag_lookup_ix_name_lower ON tag_lookup (LOWER(name));
CREATE UNIQUE INDEX IF NOT EXISTS tag_lookup_ix_name_lower_guild_id ON tag_lookup (LOWER(name), guild_id);
