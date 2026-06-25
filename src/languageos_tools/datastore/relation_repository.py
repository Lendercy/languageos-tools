from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from languageos_tools.relations.parser import ParsedRelation


@dataclass(frozen=True)
class RelationRepositoryConfig:
    db_path: Path


class RelationRepository:
    """
    SQLite repository for structured LanguageOS item relations.

    This repository is intentionally separate from the text FTS index.
    The relation index can be rebuilt from Obsidian notes.

    Responsibilities:
    - Initialize relation table.
    - Rebuild relation table from parsed Obsidian relations.
    - Query outgoing/incoming relations for debugging and future UI.
    """

    def __init__(self, config: RelationRepositoryConfig) -> None:
        self._db_path = config.db_path

    def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS item_relations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_key TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_language TEXT NOT NULL,
                    source_normalized TEXT NOT NULL,
                    source_path TEXT NOT NULL,

                    target_key TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_language TEXT NOT NULL,
                    target_normalized TEXT NOT NULL,
                    target_path TEXT NOT NULL,

                    relation_type TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    evidence TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    updated_at TEXT NOT NULL,

                    UNIQUE(source_key, target_key, relation_type)
                )
                """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_item_relations_source_key
                ON item_relations(source_key)
                """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_item_relations_target_key
                ON item_relations(target_key)
                """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_item_relations_relation_type
                ON item_relations(relation_type)
                """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_item_relations_source_normalized
                ON item_relations(source_normalized)
                """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_item_relations_target_normalized
                ON item_relations(target_normalized)
                """
            )

            conn.commit()

    def rebuild(self, relations: Iterable[ParsedRelation]) -> int:
        self.initialize()

        relation_list = list(relations)
        now = datetime.now().isoformat(timespec="seconds")

        with self._connect() as conn:
            conn.execute("DELETE FROM item_relations")

            for relation in relation_list:
                conn.execute(
                    """
                    INSERT INTO item_relations (
                        source_key,
                        source_type,
                        source_language,
                        source_normalized,
                        source_path,

                        target_key,
                        target_type,
                        target_language,
                        target_normalized,
                        target_path,

                        relation_type,
                        confidence,
                        evidence,
                        created_by,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        relation.source_key.as_string(),
                        relation.source_key.item_type,
                        relation.source_key.language,
                        relation.source_key.normalized,
                        relation.source_path,
                        relation.target_key.as_string(),
                        relation.target_key.item_type,
                        relation.target_key.language,
                        relation.target_key.normalized,
                        relation.target_path,
                        relation.relation_type.value,
                        relation.confidence,
                        relation.evidence,
                        "relation_parser",
                        now,
                    ),
                )

            conn.commit()

        return len(relation_list)

    def count(self) -> int:
        self.initialize()

        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM item_relations").fetchone()

        return int(row[0])

    def list_relations(self, limit: int = 50) -> list[dict]:
        self.initialize()

        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    source_key,
                    relation_type,
                    target_key,
                    confidence,
                    evidence,
                    source_path,
                    target_path
                FROM item_relations
                ORDER BY source_key, relation_type, target_key
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [dict(row) for row in rows]

    def search_item_keys(self, query: str, limit: int = 20) -> list[dict]:
        """
        Find item keys that appear in relation rows.

        This is intentionally relation-table based, not FTS based.
        It supports quick debugging for relation graph state.
        """

        self.initialize()
        query_like = f"%{query.strip().lower()}%"

        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                WITH relation_items AS (
                    SELECT
                        source_key AS item_key,
                        source_type AS item_type,
                        source_language AS language,
                        source_normalized AS normalized,
                        source_path AS obsidian_path
                    FROM item_relations

                    UNION

                    SELECT
                        target_key AS item_key,
                        target_type AS item_type,
                        target_language AS language,
                        target_normalized AS normalized,
                        target_path AS obsidian_path
                    FROM item_relations
                )
                SELECT DISTINCT
                    item_key,
                    item_type,
                    language,
                    normalized,
                    obsidian_path
                FROM relation_items
                WHERE
                    LOWER(item_key) LIKE ?
                    OR LOWER(normalized) LIKE ?
                    OR LOWER(obsidian_path) LIKE ?
                ORDER BY item_type, language, normalized
                LIMIT ?
                """,
                (query_like, query_like, query_like, limit),
            ).fetchall()

        return [dict(row) for row in rows]

    def get_outgoing_relations(self, item_key: str) -> list[dict]:
        self.initialize()

        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    source_key,
                    relation_type,
                    target_key,
                    confidence,
                    evidence,
                    source_path,
                    target_path
                FROM item_relations
                WHERE source_key = ?
                ORDER BY relation_type, target_key
                """,
                (item_key,),
            ).fetchall()

        return [dict(row) for row in rows]

    def get_incoming_relations(self, item_key: str) -> list[dict]:
        self.initialize()

        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    source_key,
                    relation_type,
                    target_key,
                    confidence,
                    evidence,
                    source_path,
                    target_path
                FROM item_relations
                WHERE target_key = ?
                ORDER BY relation_type, source_key
                """,
                (item_key,),
            ).fetchall()

        return [dict(row) for row in rows]

    def get_neighbors(self, item_key: str) -> dict[str, list[dict]]:
        return {
            "outgoing": self.get_outgoing_relations(item_key),
            "incoming": self.get_incoming_relations(item_key),
        }

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)