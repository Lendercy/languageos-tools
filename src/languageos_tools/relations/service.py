from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from languageos_tools.core.enums import RelationType
from languageos_tools.core.models import ItemRelation, LanguageItemKey
from languageos_tools.relations.taxonomy import RelationTaxonomy


@dataclass(frozen=True)
class RelationCandidate:
    source_key: LanguageItemKey
    target_key: LanguageItemKey
    relation_type: RelationType
    confidence: float = 1.0
    evidence: str = ""
    created_by: str = "system"

    def to_relation(self) -> ItemRelation:
        relation = ItemRelation(
            source_key=self.source_key,
            target_key=self.target_key,
            relation_type=self.relation_type,
            confidence=self.confidence,
            evidence=self.evidence,
            created_by=self.created_by,
        )
        relation.validate()
        return relation


class RelationService:
    """
    Domain service for relation handling.

    Responsibilities:
    - Validate relation types through taxonomy.
    - Normalize symmetric relations.
    - Deduplicate relations.
    - Keep relation logic out of CLI scripts and enrichment scripts.
    """

    def __init__(self, taxonomy: RelationTaxonomy) -> None:
        self._taxonomy = taxonomy

    def validate_candidate(self, candidate: RelationCandidate) -> None:
        definition = self._taxonomy.get(candidate.relation_type)

        source_type = candidate.source_key.item_type
        target_type = candidate.target_key.item_type

        if source_type not in definition.source_types:
            raise ValueError(
                f"Invalid source type '{source_type}' for relation "
                f"'{definition.id}'. Allowed: {definition.source_types}"
            )

        if target_type not in definition.target_types:
            raise ValueError(
                f"Invalid target type '{target_type}' for relation "
                f"'{definition.id}'. Allowed: {definition.target_types}"
            )

        if not 0.0 <= candidate.confidence <= 1.0:
            raise ValueError("Relation confidence must be between 0.0 and 1.0.")

    def create_relation(self, candidate: RelationCandidate) -> ItemRelation:
        self.validate_candidate(candidate)
        relation = candidate.to_relation()

        if self._taxonomy.is_symmetric(relation.relation_type):
            return self._normalize_symmetric_relation(relation)

        return relation

    def deduplicate(self, relations: Iterable[ItemRelation]) -> list[ItemRelation]:
        seen: set[tuple[str, str, str]] = set()
        result: list[ItemRelation] = []

        for relation in relations:
            normalized = (
                self._normalize_symmetric_relation(relation)
                if self._taxonomy.is_symmetric(relation.relation_type)
                else relation
            )

            key = (
                normalized.source_key.as_string(),
                normalized.target_key.as_string(),
                normalized.relation_type.value,
            )

            if key in seen:
                continue

            seen.add(key)
            result.append(normalized)

        return result

    def _normalize_symmetric_relation(self, relation: ItemRelation) -> ItemRelation:
        source = relation.source_key.as_string()
        target = relation.target_key.as_string()

        if source <= target:
            return relation

        return ItemRelation(
            source_key=relation.target_key,
            target_key=relation.source_key,
            relation_type=relation.relation_type,
            confidence=relation.confidence,
            created_by=relation.created_by,
            created_at=relation.created_at,
            evidence=relation.evidence,
        )