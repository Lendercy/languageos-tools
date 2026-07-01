from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class NoteTypeRegistryError(RuntimeError):
    """Raised when the note type registry is invalid or incomplete."""


@dataclass(frozen=True)
class LanguagePolicy:
    supported_languages: tuple[str, ...]
    meaning_language: str = "english"
    explanation_language: str = "english"

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> LanguagePolicy:
        raw_supported = data.get("supported_languages", [])
        if not isinstance(raw_supported, list) or not raw_supported:
            raise NoteTypeRegistryError(
                "default_language_policy.supported_languages must be a non-empty list."
            )

        supported_languages = tuple(
            str(language).strip().casefold()
            for language in raw_supported
            if str(language).strip()
        )

        if not supported_languages:
            raise NoteTypeRegistryError(
                "default_language_policy.supported_languages is empty after normalization."
            )

        return cls(
            supported_languages=supported_languages,
            meaning_language=str(data.get("meaning_language", "english"))
            .strip()
            .casefold(),
            explanation_language=str(data.get("explanation_language", "english"))
            .strip()
            .casefold(),
        )

    def supports_language(self, language: str) -> bool:
        return language.strip().casefold() in self.supported_languages


@dataclass(frozen=True)
class NoteTypeDefinition:
    name: str
    description: str
    category: str
    key_policy_item_type: str
    default_folder_by_language: Mapping[str, str]
    required_frontmatter: tuple[str, ...]
    optional_frontmatter: tuple[str, ...]
    body_sections: tuple[str, ...]
    language_policy: Mapping[str, str]
    relation_sections_allowed: bool
    indexable: bool
    fts_enabled: bool

    @classmethod
    def from_mapping(
        cls,
        *,
        name: str,
        data: Mapping[str, Any],
        global_language_policy: LanguagePolicy,
    ) -> NoteTypeDefinition:
        normalized_name = name.strip().casefold()
        if not normalized_name:
            raise NoteTypeRegistryError("Note type name cannot be empty.")

        key_policy_item_type = (
            str(data.get("key_policy_item_type", normalized_name)).strip().casefold()
        )

        required_frontmatter = cls._read_string_tuple(
            data=data,
            key="required_frontmatter",
            required=True,
        )
        optional_frontmatter = cls._read_string_tuple(
            data=data,
            key="optional_frontmatter",
            required=False,
        )
        body_sections = cls._read_string_tuple(
            data=data,
            key="body_sections",
            required=False,
        )

        raw_folders = data.get("default_folder_by_language", {})
        if not isinstance(raw_folders, dict):
            raise NoteTypeRegistryError(
                f"default_folder_by_language for note type {normalized_name!r} "
                "must be an object."
            )

        folders: dict[str, str] = {}
        for language, folder in raw_folders.items():
            normalized_language = str(language).strip().casefold()
            folder_value = str(folder).strip().replace("\\", "/")

            if not normalized_language or not folder_value:
                continue

            if not global_language_policy.supports_language(normalized_language):
                raise NoteTypeRegistryError(
                    f"Note type {normalized_name!r} defines unsupported language "
                    f"{normalized_language!r}."
                )

            folders[normalized_language] = folder_value

        return cls(
            name=normalized_name,
            description=str(data.get("description", "")).strip(),
            category=str(data.get("category", "language_item")).strip().casefold(),
            key_policy_item_type=key_policy_item_type,
            default_folder_by_language=folders,
            required_frontmatter=required_frontmatter,
            optional_frontmatter=optional_frontmatter,
            body_sections=body_sections,
            language_policy=cls._read_string_mapping(data.get("language_policy", {})),
            relation_sections_allowed=bool(data.get("relation_sections_allowed", True)),
            indexable=bool(data.get("indexable", True)),
            fts_enabled=bool(data.get("fts_enabled", True)),
        )

    @staticmethod
    def _read_string_tuple(
        *,
        data: Mapping[str, Any],
        key: str,
        required: bool,
    ) -> tuple[str, ...]:
        raw_value = data.get(key, [])

        if required and not raw_value:
            raise NoteTypeRegistryError(f"Missing required list field: {key}")

        if not isinstance(raw_value, list):
            raise NoteTypeRegistryError(f"{key} must be a list.")

        values = tuple(str(item).strip() for item in raw_value if str(item).strip())

        if required and not values:
            raise NoteTypeRegistryError(f"{key} cannot be empty.")

        return values

    @staticmethod
    def _read_string_mapping(value: Any) -> Mapping[str, str]:
        if value is None:
            return {}

        if not isinstance(value, dict):
            raise NoteTypeRegistryError("language_policy must be an object.")

        return {
            str(key).strip(): str(raw_value).strip().casefold()
            for key, raw_value in value.items()
            if str(key).strip() and str(raw_value).strip()
        }

    def folder_for_language(self, language: str) -> str | None:
        return self.default_folder_by_language.get(language.strip().casefold())

    def all_frontmatter_fields(self) -> tuple[str, ...]:
        seen: set[str] = set()
        fields: list[str] = []

        for field in self.required_frontmatter + self.optional_frontmatter:
            if field in seen:
                continue
            seen.add(field)
            fields.append(field)

        return tuple(fields)


@dataclass(frozen=True)
class NoteTypeRegistry:
    schema_version: str
    default_language_policy: LanguagePolicy
    note_types: Mapping[str, NoteTypeDefinition]

    EXPECTED_SCHEMA_VERSION = "note_type_registry_v1"

    @classmethod
    def load(cls, path: Path) -> NoteTypeRegistry:
        if not path.exists():
            raise FileNotFoundError(f"Note type registry does not exist: {path}")

        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_mapping(data)

    @classmethod
    def load_default(cls) -> NoteTypeRegistry:
        project_root = Path(__file__).resolve().parents[3]
        return cls.load(project_root / "configs" / "note_types.json")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> NoteTypeRegistry:
        schema_version = str(data.get("schema_version", "")).strip()

        if schema_version != cls.EXPECTED_SCHEMA_VERSION:
            raise NoteTypeRegistryError(
                f"Unsupported note type registry schema_version: {schema_version!r}. "
                f"Expected: {cls.EXPECTED_SCHEMA_VERSION!r}"
            )

        raw_language_policy = data.get("default_language_policy")
        if not isinstance(raw_language_policy, dict):
            raise NoteTypeRegistryError("Missing default_language_policy object.")

        language_policy = LanguagePolicy.from_mapping(raw_language_policy)

        raw_note_types = data.get("note_types")
        if not isinstance(raw_note_types, dict) or not raw_note_types:
            raise NoteTypeRegistryError("Missing or empty note_types object.")

        note_types: dict[str, NoteTypeDefinition] = {}
        for name, raw_definition in raw_note_types.items():
            if not isinstance(raw_definition, dict):
                raise NoteTypeRegistryError(
                    f"Note type definition for {name!r} must be an object."
                )

            definition = NoteTypeDefinition.from_mapping(
                name=str(name),
                data=raw_definition,
                global_language_policy=language_policy,
            )
            note_types[definition.name] = definition

        return cls(
            schema_version=schema_version,
            default_language_policy=language_policy,
            note_types=note_types,
        )

    def get(self, note_type: str) -> NoteTypeDefinition:
        normalized_note_type = note_type.strip().casefold()

        try:
            return self.note_types[normalized_note_type]
        except KeyError as exc:
            raise NoteTypeRegistryError(
                f"Unknown note type: {normalized_note_type!r}"
            ) from exc

    def has(self, note_type: str) -> bool:
        return note_type.strip().casefold() in self.note_types

    def list_names(self) -> tuple[str, ...]:
        return tuple(sorted(self.note_types))

    def supported_languages(self) -> tuple[str, ...]:
        return self.default_language_policy.supported_languages

    def supports_language(self, language: str) -> bool:
        return self.default_language_policy.supports_language(language)

    def definitions(self) -> tuple[NoteTypeDefinition, ...]:
        return tuple(self.note_types[name] for name in self.list_names())


def describe_registry(registry: NoteTypeRegistry) -> str:
    lines: list[str] = []

    lines.append("Note Type Registry")
    lines.append("=" * 80)
    lines.append(f"Schema version     : {registry.schema_version}")
    lines.append(
        "Supported languages: "
        + ", ".join(registry.default_language_policy.supported_languages)
    )
    lines.append(
        f"Meaning language   : {registry.default_language_policy.meaning_language}"
    )
    lines.append(
        f"Explanation language: {registry.default_language_policy.explanation_language}"
    )
    lines.append("-" * 80)

    for definition in registry.definitions():
        lines.append(f"- {definition.name}")
        lines.append(f"    category              : {definition.category}")
        lines.append(f"    key_policy_item_type  : {definition.key_policy_item_type}")
        lines.append(f"    indexable             : {definition.indexable}")
        lines.append(f"    fts_enabled           : {definition.fts_enabled}")
        lines.append(
            "    required_frontmatter  : " + ", ".join(definition.required_frontmatter)
        )
        lines.append(
            "    optional_frontmatter  : " + ", ".join(definition.optional_frontmatter)
        )
        lines.append(
            "    body_sections         : " + ", ".join(definition.body_sections)
        )

        if definition.default_folder_by_language:
            lines.append("    folders:")
            for language, folder in sorted(
                definition.default_folder_by_language.items()
            ):
                lines.append(f"      {language}: {folder}")

    return "\n".join(lines)
