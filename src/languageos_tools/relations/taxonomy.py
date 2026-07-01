from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from languageos_tools.core.enums import RelationType


class RelationTaxonomyError(ValueError):
    pass


@dataclass(frozen=True)
class RelationTypeDefinition:
    id: str
    label: str
    category: str
    description: str
    source_types: tuple[str, ...]
    target_types: tuple[str, ...]
    symmetric: bool
    enabled: bool = True

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RelationTypeDefinition:
        required_keys = {
            "id",
            "label",
            "category",
            "description",
            "source_types",
            "target_types",
            "symmetric",
            "enabled",
        }

        missing = sorted(required_keys - set(payload.keys()))

        if missing:
            raise RelationTaxonomyError(
                f"Relation type definition is missing keys: {', '.join(missing)}"
            )

        return cls(
            id=str(payload["id"]).strip(),
            label=str(payload["label"]).strip(),
            category=str(payload["category"]).strip(),
            description=str(payload["description"]).strip(),
            source_types=tuple(str(item).strip() for item in payload["source_types"]),
            target_types=tuple(str(item).strip() for item in payload["target_types"]),
            symmetric=bool(payload["symmetric"]),
            enabled=bool(payload["enabled"]),
        )

    def validate(self) -> None:
        if not self.id:
            raise RelationTaxonomyError("Relation type id cannot be empty.")

        if not self.label:
            raise RelationTaxonomyError(f"Relation type {self.id} has empty label.")

        if not self.category:
            raise RelationTaxonomyError(f"Relation type {self.id} has empty category.")

        if not self.source_types:
            raise RelationTaxonomyError(f"Relation type {self.id} has no source_types.")

        if not self.target_types:
            raise RelationTaxonomyError(f"Relation type {self.id} has no target_types.")


@dataclass(frozen=True)
class RelationTaxonomy:
    schema_version: str
    definitions: dict[str, RelationTypeDefinition]

    @classmethod
    def load(cls, path: Path) -> RelationTaxonomy:
        if not path.exists():
            raise FileNotFoundError(f"Relation taxonomy file not found: {path}")

        payload = json.loads(path.read_text(encoding="utf-8"))

        schema_version = str(payload.get("schema_version", "1.0")).strip()
        raw_definitions = payload.get("relation_types", [])

        if not isinstance(raw_definitions, list):
            raise RelationTaxonomyError("relation_types must be a list.")

        definitions: dict[str, RelationTypeDefinition] = {}

        for raw_definition in raw_definitions:
            definition = RelationTypeDefinition.from_dict(raw_definition)
            definition.validate()

            if definition.id in definitions:
                raise RelationTaxonomyError(
                    f"Duplicate relation type id: {definition.id}"
                )

            definitions[definition.id] = definition

        taxonomy = cls(
            schema_version=schema_version,
            definitions=definitions,
        )

        taxonomy.validate_against_enum()

        return taxonomy

    def validate_against_enum(self) -> None:
        enum_values = {item.value for item in RelationType}

        for relation_id in self.definitions:
            if relation_id not in enum_values:
                raise RelationTaxonomyError(
                    f"Relation type '{relation_id}' exists in taxonomy JSON "
                    f"but not in RelationType enum."
                )

    def get(self, relation_type: str | RelationType) -> RelationTypeDefinition:
        relation_id = self.normalize_relation_id(relation_type)

        if relation_id not in self.definitions:
            raise RelationTaxonomyError(f"Unknown relation type: {relation_id}")

        definition = self.definitions[relation_id]

        if not definition.enabled:
            raise RelationTaxonomyError(f"Relation type is disabled: {relation_id}")

        return definition

    def exists(self, relation_type: str | RelationType) -> bool:
        relation_id = self.normalize_relation_id(relation_type)
        return relation_id in self.definitions

    def is_symmetric(self, relation_type: str | RelationType) -> bool:
        return self.get(relation_type).symmetric

    def enabled_definitions(self) -> list[RelationTypeDefinition]:
        return [
            definition for definition in self.definitions.values() if definition.enabled
        ]

    def normalize_relation_id(self, relation_type: str | RelationType) -> str:
        if isinstance(relation_type, RelationType):
            return relation_type.value

        return str(relation_type).strip().lower()
