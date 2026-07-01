from __future__ import annotations

from pathlib import Path

from languageos_tools.core.enums import RelationType
from languageos_tools.core.models import LanguageItemKey
from languageos_tools.datastore.relation_repository import (
    RelationRepository,
    RelationRepositoryConfig,
)
from languageos_tools.relations.parser import ParsedRelation


def test_relation_repository_rebuild_and_query(tmp_path: Path) -> None:
    db_path = tmp_path / "languageos.db"

    repository = RelationRepository(
        RelationRepositoryConfig(
            db_path=db_path,
        )
    )

    source_key = LanguageItemKey(
        item_type="sentence",
        language="german",
        normalized="trotzdem lerne ich deutsch",
    )
    target_key = LanguageItemKey(
        item_type="vocabulary",
        language="german",
        normalized="trotzdem",
    )

    relation = ParsedRelation(
        source_key=source_key,
        target_key=target_key,
        relation_type=RelationType.CONTAINS_VOCABULARY,
        confidence=1.0,
        evidence="test",
        source_path="Sentences/German/Trotzdem lerne ich Deutsch",
        target_path="Vocabulary/German/trotzdem",
    )

    inserted = repository.rebuild([relation])

    assert inserted == 1
    assert repository.count() == 1

    matches = repository.search_item_keys("trotzdem")
    assert len(matches) == 2

    neighbors = repository.get_neighbors(source_key.as_string())
    assert len(neighbors["outgoing"]) == 1
    assert len(neighbors["incoming"]) == 0

    outgoing = neighbors["outgoing"][0]
    assert outgoing["relation_type"] == "contains_vocabulary"
    assert outgoing["target_key"] == target_key.as_string()


def test_relation_repository_rebuild_is_replace_all(tmp_path: Path) -> None:
    db_path = tmp_path / "languageos.db"

    repository = RelationRepository(
        RelationRepositoryConfig(
            db_path=db_path,
        )
    )

    source_key = LanguageItemKey(
        item_type="sentence",
        language="german",
        normalized="a",
    )
    target_key = LanguageItemKey(
        item_type="vocabulary",
        language="german",
        normalized="b",
    )

    relation = ParsedRelation(
        source_key=source_key,
        target_key=target_key,
        relation_type=RelationType.CONTAINS_VOCABULARY,
        confidence=1.0,
        evidence="test",
        source_path="Sentences/German/A",
        target_path="Vocabulary/German/B",
    )

    repository.rebuild([relation])
    assert repository.count() == 1

    repository.rebuild([])
    assert repository.count() == 0
