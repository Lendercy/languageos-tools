from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    type TEXT NOT NULL,
    language TEXT NOT NULL,

    text TEXT NOT NULL,
    normalized TEXT NOT NULL,

    status TEXT NOT NULL DEFAULT 'new',
    anki_status TEXT NOT NULL DEFAULT 'none',
    anki_note_id TEXT,

    level TEXT DEFAULT 'unknown',
    source_type TEXT DEFAULT 'unknown',
    source TEXT,

    seen_count INTEGER NOT NULL DEFAULT 0,
    first_seen TEXT,
    last_seen TEXT,

    difficulty TEXT DEFAULT 'unknown',
    confidence TEXT DEFAULT 'unknown',

    obsidian_path TEXT,
    obsidian_link TEXT,

    created_at TEXT,
    updated_at TEXT,

    UNIQUE(type, language, normalized)
);

CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS item_topics (
    item_id INTEGER NOT NULL,
    topic_id INTEGER NOT NULL,

    PRIMARY KEY (item_id, topic_id),

    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
    FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS item_skills (
    item_id INTEGER NOT NULL,
    skill_id INTEGER NOT NULL,

    PRIMARY KEY (item_id, skill_id),

    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
    FOREIGN KEY (skill_id) REFERENCES skills(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,
    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,

    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    source_type TEXT NOT NULL,
    title TEXT NOT NULL,
    path TEXT,
    language TEXT DEFAULT 'unknown',

    created_at TEXT,
    updated_at TEXT,

    UNIQUE(source_type, title, path)
);

CREATE TABLE IF NOT EXISTS contexts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    item_id INTEGER NOT NULL,
    source_id INTEGER,

    context_text TEXT,
    timestamp_start TEXT,
    timestamp_end TEXT,

    created_at TEXT,

    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    from_item_id INTEGER NOT NULL,
    to_item_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL,

    created_at TEXT,

    FOREIGN KEY (from_item_id) REFERENCES items(id) ON DELETE CASCADE,
    FOREIGN KEY (to_item_id) REFERENCES items(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    item_id INTEGER NOT NULL,
    model_name TEXT NOT NULL,
    vector_json TEXT NOT NULL,

    created_at TEXT,

    UNIQUE(item_id, model_name),

    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    run_type TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    message TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS search_documents_fts USING fts5(
    item_id UNINDEXED,
    doc_type UNINDEXED,
    language UNINDEXED,
    status UNINDEXED,
    title,
    body,
    path UNINDEXED,
    obsidian_link UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE INDEX IF NOT EXISTS idx_items_type_language ON items(type, language);
CREATE INDEX IF NOT EXISTS idx_items_normalized ON items(normalized);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
CREATE INDEX IF NOT EXISTS idx_items_anki_status ON items(anki_status);
CREATE INDEX IF NOT EXISTS idx_items_seen_count ON items(seen_count);
CREATE INDEX IF NOT EXISTS idx_aliases_normalized ON aliases(normalized_alias);
"""


def connect_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")

    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def get_or_create_lookup_id(
    conn: sqlite3.Connection,
    table: str,
    name: str,
) -> int:
    normalized_name = name.strip()

    if not normalized_name:
        raise ValueError("Lookup name cannot be empty.")

    conn.execute(
        f"INSERT OR IGNORE INTO {table} (name) VALUES (?)",
        (normalized_name,),
    )

    row = conn.execute(
        f"SELECT id FROM {table} WHERE name = ?",
        (normalized_name,),
    ).fetchone()

    if row is None:
        raise RuntimeError(f"Failed to get lookup id from {table}: {name}")

    return int(row["id"])