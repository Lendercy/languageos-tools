from __future__ import annotations

import sqlite3
from pathlib import Path

from languageos_tools.core.enums import RelationType
from languageos_tools.core.models import LanguageItemKey
from languageos_tools.datastore.relation_repository import (
    RelationRepository,
    RelationRepositoryConfig,
)
from languageos_tools.relations.parser import ParsedRelation
from languageos_tools.ui.services.workspace_service import WorkspaceService


def create_language_items_table(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE language_items (
                item_key TEXT NOT NULL PRIMARY KEY,
                item_type TEXT NOT NULL,
                language TEXT NOT NULL,
                normalized TEXT NOT NULL,
                title TEXT NOT NULL,
                file_path TEXT NOT NULL,
                text TEXT NOT NULL
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO language_items (
                item_key,
                item_type,
                language,
                normalized,
                title,
                file_path,
                text
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "vocabulary|german|trotzdem",
                    "vocabulary",
                    "german",
                    "trotzdem",
                    "trotzdem",
                    "Vocabulary/German/trotzdem",
                    "nevertheless, however",
                ),
                (
                    "grammar|german|contrast connectors",
                    "grammar",
                    "german",
                    "contrast connectors",
                    "Contrast connectors",
                    "Grammar/German/Contrast connectors",
                    "aber, trotzdem, obwohl",
                ),
            ],
        )
        connection.commit()


def create_relation_index(db_path: Path) -> None:
    repository = RelationRepository(
        RelationRepositoryConfig(
            db_path=db_path,
        )
    )

    relation = ParsedRelation(
        source_key=LanguageItemKey(
            item_type="vocabulary",
            language="german",
            normalized="trotzdem",
        ),
        target_key=LanguageItemKey(
            item_type="grammar",
            language="german",
            normalized="contrast connectors",
        ),
        relation_type=RelationType.USES_GRAMMAR,
        confidence=1.0,
        evidence="test",
        source_path="Vocabulary/German/trotzdem",
        target_path="Grammar/German/Contrast connectors",
    )

    repository.rebuild([relation])


def test_workspace_service_lookup_item_and_outgoing_relations(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "languageos.db"

    create_language_items_table(db_path)
    create_relation_index(db_path)

    service = WorkspaceService(db_path=db_path)

    result = service.lookup(query="trotzdem")

    assert result.has_matches is True
    assert result.selected_item is not None
    assert result.selected_item.item_key == "vocabulary|german|trotzdem"
    assert result.selected_item.title == "trotzdem"

    assert len(result.outgoing_relations) == 1
    assert result.outgoing_relations[0].relation_type == "uses_grammar"
    assert result.outgoing_relations[0].connected_key == (
        "grammar|german|contrast connectors"
    )
    assert result.outgoing_relations[0].connected_label == "contrast connectors"

    assert result.incoming_relations == ()


def test_workspace_service_lookup_item_and_incoming_relations(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "languageos.db"

    create_language_items_table(db_path)
    create_relation_index(db_path)

    service = WorkspaceService(db_path=db_path)

    result = service.lookup(query="Contrast connectors")

    assert result.has_matches is True
    assert result.selected_item is not None
    assert result.selected_item.item_key == "grammar|german|contrast connectors"

    assert result.outgoing_relations == ()
    assert len(result.incoming_relations) == 1
    assert result.incoming_relations[0].relation_type == "uses_grammar"
    assert result.incoming_relations[0].connected_key == "vocabulary|german|trotzdem"


def test_workspace_service_empty_query_returns_empty_view(tmp_path: Path) -> None:
    db_path = tmp_path / "languageos.db"
    service = WorkspaceService(db_path=db_path)

    result = service.lookup(query="   ")

    assert result.has_matches is False
    assert result.items == ()
    assert result.selected_item is None
    assert result.outgoing_relations == ()
    assert result.incoming_relations == ()
