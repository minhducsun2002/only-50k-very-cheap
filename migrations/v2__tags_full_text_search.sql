CREATE VIRTUAL TABLE IF NOT EXISTS tag_lookup_search USING fts5(
    name,
    content='tag_lookup',
    content_rowid='id',
    tokenize='simplify casefold true strip true unicodewords' -- APSW tokenizers, not default with SQLite!
);

CREATE TRIGGER fts5sync_tag_lookup_to_tag_lookup_search_insert AFTER INSERT ON tag_lookup
BEGIN
    INSERT INTO tag_lookup_search(rowid, name) VALUES (new.id, new.name);
END;

CREATE TRIGGER fts5sync_tag_lookup_to_tag_lookup_search_delete AFTER DELETE ON tag_lookup
BEGIN
    INSERT INTO tag_lookup_search(tag_lookup_search, rowid, name) VALUES ('delete', old.id, old.name);
END;

CREATE TRIGGER fts5sync_tag_lookup_to_tag_lookup_search_update AFTER UPDATE ON tag_lookup
BEGIN
    INSERT INTO tag_lookup_search(tag_lookup_search, rowid, name) VALUES ('delete', old.id, old.name);
    INSERT INTO tag_lookup_search(rowid, name) VALUES (new.id, new.name);
END;

INSERT INTO tag_lookup_search(tag_lookup_search) VALUES ('rebuild');
