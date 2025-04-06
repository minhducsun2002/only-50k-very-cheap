CREATE TABLE IF NOT EXISTS racism_pity_counter(
    id INTEGER PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    count BIGINT NOT NULL,
    UNIQUE(guild_id, user_id)
);
CREATE INDEX racism_pity_counter_ix_guild_id ON racism_pity_counter(guild_id);
CREATE INDEX racism_pity_counter_ix_user_id ON racism_pity_counter(user_id);
CREATE INDEX racism_pity_counter_uq_ix_guild_id_user_id ON racism_pity_counter(guild_id, user_id);
