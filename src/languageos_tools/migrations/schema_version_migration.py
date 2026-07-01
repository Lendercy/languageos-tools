from __future__ import annotations

from dataclasses import dataclass

from languageos_tools.core.frontmatter import FrontmatterParser
from languageos_tools.core.models import DEFAULT_SCHEMA_VERSION, FrontmatterDocument
from languageos_tools.migrations.migration_runner import MigrationContext
from languageos_tools.obsidian.note import VaultNote


@dataclass(frozen=True)
class SchemaVersionMigration:
    """
    Adds schema_version to atomic LanguageOS notes.

    This migration is intentionally conservative:
    - It only processes notes with frontmatter.
    - It only processes notes with a `type` field.
    - It does not overwrite existing schema_version.
    - It preserves body content.
    """

    target_schema_version: str = DEFAULT_SCHEMA_VERSION

    @property
    def name(self) -> str:
        return f"Schema Version Migration v{self.target_schema_version}"

    def should_process(self, note: VaultNote) -> bool:
        parser = FrontmatterParser()
        document = note.parse(parser)

        if not document.has_frontmatter:
            return False

        note_type = document.get_str("type")

        if not note_type:
            return False

        return True

    def migrate_note(
        self, note: VaultNote, context: MigrationContext
    ) -> VaultNote | None:
        parser = FrontmatterParser()
        document = note.parse(parser)

        if not document.has_frontmatter:
            return None

        note_type = document.get_str("type")

        if not note_type:
            return None

        current_schema_version = document.get_str("schema_version")

        if current_schema_version:
            return None

        new_metadata = dict(document.metadata)
        new_metadata["schema_version"] = self.target_schema_version

        new_document = FrontmatterDocument(
            metadata=new_metadata,
            body=document.body,
            has_frontmatter=True,
        )

        return note.with_document(new_document, parser=parser)
