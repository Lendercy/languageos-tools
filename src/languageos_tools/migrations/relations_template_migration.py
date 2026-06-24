from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from languageos_tools.core.frontmatter import FrontmatterParser
from languageos_tools.core.models import FrontmatterDocument
from languageos_tools.migrations.migration_runner import MigrationContext
from languageos_tools.obsidian.note import VaultNote


RELATIONS_TEMPLATE_VERSION = "1.0"


ITEM_RELATION_SECTIONS: dict[str, tuple[str, ...]] = {
    "vocabulary": (
        "uses_grammar",
        "example_of",
        "similar_to",
        "opposite_of",
        "contrast_with",
        "confusable_with",
        "translation_of",
        "translation_variant_of",
        "formal_variant_of",
        "informal_variant_of",
        "slang_variant_of",
        "register_variant_of",
    ),
    "sentence": (
        "contains_vocabulary",
        "uses_grammar",
        "derived_from",
        "similar_to",
        "opposite_of",
        "contrast_with",
        "confusable_with",
        "negative_counterpart",
        "translation_of",
        "translation_variant_of",
    ),
    "grammar": (
        "similar_to",
        "contrast_with",
        "confusable_with",
        "grammar_contrast_with",
    ),
}


SENSE_SUPPORTED_TYPES = {
    "vocabulary",
    "sentence",
}


@dataclass(frozen=True)
class RelationsTemplateMigration:
    """
    Adds future-proof relation/sense scaffold sections to atomic LanguageOS notes.

    Design rules:
    - Non-destructive: never removes or rewrites existing user content.
    - Conservative: only processes vocabulary/sentence/grammar notes.
    - Idempotent: running it multiple times should not keep changing notes.
    - Template-versioned: uses `relations_template_version` to track applied state.
    - Existing `## Meaning` sections are preserved.
    - `## Meanings / Senses` is only created when no meaning section exists yet.
    """

    template_version: str = RELATIONS_TEMPLATE_VERSION

    @property
    def name(self) -> str:
        return f"Relations and Senses Template Migration v{self.template_version}"

    def should_process(self, note: VaultNote) -> bool:
        parser = FrontmatterParser()
        document = note.parse(parser)

        if not document.has_frontmatter:
            return False

        item_type = document.get_str("type").strip().lower()

        if item_type not in ITEM_RELATION_SECTIONS:
            return False

        return True

    def migrate_note(self, note: VaultNote, context: MigrationContext) -> VaultNote | None:
        parser = FrontmatterParser()
        document = note.parse(parser)

        item_type = document.get_str("type").strip().lower()

        if item_type not in ITEM_RELATION_SECTIONS:
            return None

        changed = False
        new_metadata = dict(document.metadata)
        new_body = document.body.rstrip()

        if new_metadata.get("relations_template_version") != self.template_version:
            new_metadata["relations_template_version"] = self.template_version
            changed = True

        if self._should_add_senses_section(item_type, new_body):
            new_body = self._append_section(
                body=new_body,
                section=self._build_senses_section(item_type),
            )
            changed = True

        if not self._has_heading(new_body, "Relations", level=2):
            new_body = self._append_section(
                body=new_body,
                section=self._build_relations_section(
                    item_type=item_type,
                    relation_types=ITEM_RELATION_SECTIONS[item_type],
                ),
            )
            changed = True

        if not changed:
            return None

        new_document = FrontmatterDocument(
            metadata=new_metadata,
            body=new_body.rstrip() + "\n",
            has_frontmatter=True,
        )

        return note.with_document(new_document, parser=parser)

    def _should_add_senses_section(self, item_type: str, body: str) -> bool:
        if item_type not in SENSE_SUPPORTED_TYPES:
            return False

        if self._has_heading(body, "Meanings / Senses", level=2):
            return False

        # Preserve existing meaning sections for now.
        # A later dedicated migration can convert `## Meaning`
        # into `## Meanings / Senses` after preview/review.
        if self._has_heading(body, "Meaning", level=2):
            return False

        return True

    def _build_senses_section(self, item_type: str) -> str:
        if item_type == "vocabulary":
            return "\n".join(
                [
                    "## Meanings / Senses",
                    "",
                    "### Sense 1 — main usage",
                    "",
                    "Main meaning:",
                    "- TODO",
                    "",
                    "Usage:",
                    "- TODO",
                    "",
                    "Examples:",
                    "- TODO",
                ]
            )

        if item_type == "sentence":
            return "\n".join(
                [
                    "## Meaning Variants",
                    "",
                    "### Variant 1 — main interpretation",
                    "",
                    "Main meaning:",
                    "- TODO",
                    "",
                    "Alternative translations:",
                    "- TODO",
                    "",
                    "Usage note:",
                    "- TODO",
                ]
            )

        return ""

    def _build_relations_section(
        self,
        item_type: str,
        relation_types: Iterable[str],
    ) -> str:
        lines: list[str] = [
            "## Relations",
            "",
            "<!--",
            "Controlled relation section.",
            "Add Obsidian links under the relevant relation type.",
            "Example:",
            "- [[Vocabulary/German/trotzdem|trotzdem]]",
            "-->",
            "",
        ]

        for relation_type in relation_types:
            lines.append(f"### {relation_type}")
            lines.append("")

        return "\n".join(lines).rstrip()

    def _append_section(self, body: str, section: str) -> str:
        body = body.rstrip()
        section = section.strip()

        if not section:
            return body

        if not body:
            return section + "\n"

        return body + "\n\n" + section + "\n"

    def _has_heading(self, body: str, heading: str, level: int) -> bool:
        hashes = "#" * level
        pattern = rf"(?im)^{re.escape(hashes)}\s+{re.escape(heading)}\s*$"
        return re.search(pattern, body) is not None