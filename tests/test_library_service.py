from __future__ import annotations

import sqlite3
from pathlib import Path

from languageos_tools.ui.services.library_service import (
    LibraryFilter,
    LibraryService,
)


def test_library_service_returns_empty_view_for_missing_database(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "missing.db"
    service = LibraryService(db_path=db_path)

    view = service.lookup()

    assert view.db_exists is False
    assert view.items == ()
    assert view.facets.languages == ()


def test_library_service_filters_items_by_core_metadata(tmp_path: Path) -> None:
    db_path = tmp_path / "languageos.db"
    _create_library_test_db(db_path)

    service = LibraryService(db_path=db_path)

    view = service.lookup(
        LibraryFilter(
            language="german",
            item_type="vocabulary",
            status="learning",
            anki_status="none",
            level="a2",
            source_type="stt",
        )
    )

    assert view.db_exists is True
    assert len(view.items) == 1

    item = view.items[0]

    assert item.item_key == "vocabulary|german|trotzdem"
    assert item.item_type == "vocabulary"
    assert item.language == "german"
    assert item.normalized == "trotzdem"
    assert item.status == "learning"
    assert item.anki_status == "none"
    assert item.level == "a2"
    assert item.source_type == "stt"
    assert item.review_status == "active"
    assert item.review_priority == "normal"
    assert item.topics == ("connectors", "contrast")
    assert item.skills == ("listening", "reading")


def test_library_service_filters_items_by_topic_skill_and_review_state(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "languageos.db"
    _create_library_test_db(db_path)

    service = LibraryService(db_path=db_path)

    view = service.lookup(
        LibraryFilter(
            topic="contrast",
            skill="reading",
            review_status="active",
            review_priority="normal",
            query="trotz",
        )
    )

    assert len(view.items) == 1
    assert view.items[0].item_key == "vocabulary|german|trotzdem"


def test_library_service_loads_facets(tmp_path: Path) -> None:
    db_path = tmp_path / "languageos.db"
    _create_library_test_db(db_path)

    service = LibraryService(db_path=db_path)
    view = service.lookup()

    assert view.facets.languages == ("english", "german")
    assert view.facets.item_types == ("sentence", "vocabulary")
    assert view.facets.statuses == ("learning",)
    assert view.facets.anki_statuses == ("none",)
    assert view.facets.levels == ("a2", "b1")
    assert view.facets.source_types == ("manual", "stt")
    assert view.facets.review_statuses == ("active",)
    assert view.facets.review_priorities == ("normal",)
    assert view.facets.topics == ("connectors", "contrast")
    assert view.facets.skills == ("listening", "reading", "writing")


def _create_library_test_db(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE items (
                id INTEGER PRIMARY KEY,
                type TEXT,
                language TEXT,
                text TEXT,
                normalized TEXT,
                status TEXT,
                anki_status TEXT,
                anki_note_id TEXT,
                level TEXT,
                source_type TEXT,
                source TEXT,
                seen_count INTEGER,
                first_seen TEXT,
                last_seen TEXT,
                difficulty TEXT,
                confidence TEXT,
                obsidian_path TEXT,
                obsidian_link TEXT,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE item_activity (
                item_key TEXT,
                type TEXT,
                language TEXT,
                normalized TEXT,
                access_count INTEGER,
                last_accessed_at TEXT,
                review_count INTEGER,
                last_reviewed_at TEXT,
                review_status TEXT,
                review_priority TEXT,
                stale_after_days INTEGER,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE topics (
                id INTEGER PRIMARY KEY,
                name TEXT
            );

            CREATE TABLE skills (
                id INTEGER PRIMARY KEY,
                name TEXT
            );

            CREATE TABLE item_topics (
                item_id INTEGER,
                topic_id INTEGER
            );

            CREATE TABLE item_skills (
                item_id INTEGER,
                skill_id INTEGER
            );
            """
        )

        conn.execute(
            """
            INSERT INTO items (
                id,
                type,
                language,
                text,
                normalized,
                status,
                anki_status,
                level,
                source_type,
                source,
                seen_count,
                obsidian_path
            )
            VALUES (
                1,
                'vocabulary',
                'german',
                'trotzdem',
                'trotzdem',
                'learning',
                'none',
                'a2',
                'stt',
                'manual test',
                1,
                'D:\\LanguageOS\\Obsidian\\Vocabulary\\German\\trotzdem.md'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO items (
                id,
                type,
                language,
                text,
                normalized,
                status,
                anki_status,
                level,
                source_type,
                source,
                seen_count,
                obsidian_path
            )
            VALUES (
                2,
                'sentence',
                'english',
                'I keep learning anyway.',
                'i keep learning anyway',
                'learning',
                'none',
                'b1',
                'manual',
                'manual test',
                1,
                'D:\\LanguageOS\\Obsidian\\Sentences\\English\\anyway.md'
            )
            """
        )

        conn.execute(
            """
            INSERT INTO item_activity (
                item_key,
                type,
                language,
                normalized,
                access_count,
                review_count,
                review_status,
                review_priority,
                stale_after_days
            )
            VALUES (
                'vocabulary|german|trotzdem',
                'vocabulary',
                'german',
                'trotzdem',
                4,
                1,
                'active',
                'normal',
                14
            )
            """
        )
        conn.execute(
            """
            INSERT INTO item_activity (
                item_key,
                type,
                language,
                normalized,
                access_count,
                review_count,
                review_status,
                review_priority,
                stale_after_days
            )
            VALUES (
                'sentence|english|i keep learning anyway',
                'sentence',
                'english',
                'i keep learning anyway',
                2,
                1,
                'active',
                'normal',
                14
            )
            """
        )

        conn.executemany(
            "INSERT INTO topics (id, name) VALUES (?, ?)",
            [
                (1, "contrast"),
                (2, "connectors"),
            ],
        )
        conn.executemany(
            "INSERT INTO skills (id, name) VALUES (?, ?)",
            [
                (1, "reading"),
                (2, "listening"),
                (3, "writing"),
            ],
        )
        conn.executemany(
            "INSERT INTO item_topics (item_id, topic_id) VALUES (?, ?)",
            [
                (1, 1),
                (1, 2),
            ],
        )
        conn.executemany(
            "INSERT INTO item_skills (item_id, skill_id) VALUES (?, ?)",
            [
                (1, 1),
                (1, 2),
                (2, 3),
            ],
        )