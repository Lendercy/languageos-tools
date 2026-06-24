from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from languageos_tools.core.frontmatter import FrontmatterParser
from languageos_tools.core.models import FrontmatterDocument
from languageos_tools.migrations.migration_runner import MigrationContext
from languageos_tools.obsidian.note import VaultNote


RELATIONS_TEMPLATE_VERSION = "1.1"


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


RELATION_LABELS: dict[str, str] = {
    "contains_vocabulary": "Contains Vocabulary",
    "uses_grammar": "Uses Grammar",
    "example_of": "Example Of",
    "source_of": "Source Of",
    "derived_from": "Derived From",
    "similar_to": "Similar To",
    "opposite_of": "Opposite Of",
    "contrast_with": "Contrast With",
    "confusable_with": "Confusable With",
    "negative_counterpart": "Negative Counterpart",
    "translation_of": "Translation Of",
    "translation_variant_of": "Translation Variant Of",
    "formal_variant_of": "Formal Variant Of",
    "informal_variant_of": "Informal Variant Of",
    "slang_variant_of": "Slang Variant Of",
    "register_variant_of": "Register Variant Of",
    "grammar_contrast_with": "Grammar Contrast With",
}


SENSE_SUPPORTED_TYPES = {
    "vocabulary",
    "sentence",
}


@dataclass(frozen=True)
class RelationsTemplateMigration:
    """
    Adds or upgrades future-proof relation/sense scaffold sections.

    Design rules:
    - Non-destructive.
    - Only processes vocabulary/sentence/grammar notes.
    - Idempotent.
    - Uses relations_template_version.
    - Preserves existing user-written relation links.
    - Replaces old auto-generated v1.0 relation scaffold.
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

        return item_type in ITEM_RELATION_SECTIONS

    def migrate_note(self, note: VaultNote, context: MigrationContext) -> VaultNote | None:
        parser = FrontmatterParser()
        document = note.parse(parser)

        item_type = document.get_str("type").strip().lower()

        if item_type not in ITEM_RELATION_SECTIONS:
            return None

        changed = False
        new_metadata = dict(document.metadata)
        new_body = document.body.rstrip()

        current_template_version = str(
            new_metadata.get("relations_template_version") or ""
        ).strip()

        if current_template_version != self.template_version:
            new_metadata["relations_template_version"] = self.template_version
            changed = True

        if self._should_add_senses_section(item_type, new_body):
            new_body = self._append_section(
                body=new_body,
                section=self._build_senses_section(item_type),
            )
            changed = True

        desired_relations_section = self._build_relations_section(
            relation_types=ITEM_RELATION_SECTIONS[item_type],
        )

        if not self._has_heading(new_body, "Relations", level=2):
            new_body = self._append_section(
                body=new_body,
                section=desired_relations_section,
            )
            changed = True
        else:
            existing_relations_section = self._extract_section(
                body=new_body,
                heading="Relations",
                level=2,
            )

            if self._is_auto_generated_empty_relations_section(existing_relations_section):
                new_body = self._replace_section(
                    body=new_body,
                    heading="Relations",
                    level=2,
                    replacement=desired_relations_section,
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

        if item_type == "vocabulary":
            if self._has_heading(body, "Meanings / Senses", level=2):
                return False

            if self._has_heading(body, "Meaning", level=2):
                return False

            return True

        if item_type == "sentence":
            if self._has_heading(body, "Meaning Variants", level=2):
                return False

            if self._has_heading(body, "Meaning", level=2):
                return False

            return True

        return False

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

    def _build_relations_section(self, relation_types: Iterable[str]) -> str:
        lines: list[str] = [
            "## Relations",
            "",
            "Add Obsidian links under the relevant relation type.",
            "Use the `relation_type` line as the machine-readable id.",
            "",
        ]

        for relation_type in relation_types:
            label = RELATION_LABELS.get(
                relation_type,
                self._humanize_relation_id(relation_type),
            )
            lines.append(f"### {label}")
            lines.append("")
            lines.append(f"relation_type: `{relation_type}`")
            lines.append("")
            lines.append("- TODO")
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

    def _extract_section(self, body: str, heading: str, level: int) -> str:
        hashes = "#" * level
        pattern = (
            rf"(?ims)^"
            rf"{re.escape(hashes)}\s+{re.escape(heading)}\s*$"
            rf"\n(.*?)(?=^##\s+|\Z)"
        )

        match = re.search(pattern, body)

        if not match:
            return ""

        return match.group(1).strip()

    def _replace_section(
        self,
        body: str,
        heading: str,
        level: int,
        replacement: str,
    ) -> str:
        hashes = "#" * level
        pattern = (
            rf"(?ims)^"
            rf"{re.escape(hashes)}\s+{re.escape(heading)}\s*$"
            rf"\n.*?(?=^##\s+|\Z)"
        )

        return re.sub(pattern, replacement.strip(), body).rstrip()

    def _is_auto_generated_empty_relations_section(self, section: str) -> bool:
        cleaned = self._remove_html_comments(section).strip()

        if not cleaned:
            return True

        lines = [
            line.strip()
            for line in cleaned.splitlines()
            if line.strip()
        ]

        real_content_lines: list[str] = []

        for line in lines:
            if line.startswith("Add Obsidian links"):
                continue

            if line.startswith("Use the `relation_type`"):
                continue

            if re.match(r"^###\s+[A-Za-z0-9_ ]+$", line):
                continue

            if line.startswith("relation_type:"):
                continue

            if line == "- TODO":
                continue

            if line in {"<!--", "-->"}:
                continue

            # Old v1.0 example line. It is not user data.
            if line == "- [[Vocabulary/German/trotzdem|trotzdem]]":
                continue

            if line == "Controlled relation section.":
                continue

            if line == "Example:":
                continue

            real_content_lines.append(line)

        # If user added actual relation links outside the old example,
        # preserve the section.
        for line in real_content_lines:
            if "[[" in line and "]]" in line:
                return False

        return len(real_content_lines) == 0

    def _remove_html_comments(self, text: str) -> str:
        return re.sub(r"(?is)<!--.*?-->", "", text)

    def _humanize_relation_id(self, relation_id: str) -> str:
        return relation_id.replace("_", " ").title()