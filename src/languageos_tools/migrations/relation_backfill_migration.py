from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from languageos_tools.core.frontmatter import FrontmatterParser
from languageos_tools.core.models import FrontmatterDocument
from languageos_tools.migrations.migration_runner import MigrationContext
from languageos_tools.migrations.relations_template_migration import (
    ITEM_RELATION_SECTIONS,
    RELATION_LABELS,
)
from languageos_tools.obsidian.note import VaultNote

RELATION_BACKFILL_VERSION = "1.0"

WIKILINK_PATTERN = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]")

LEGACY_SECTION_RELATION_MAP: dict[str, str] = {
    "contains vocabulary": "contains_vocabulary",
    "grammar / pattern": "uses_grammar",
    "related grammar": "uses_grammar",
    "similar sentences": "similar_to",
    "similar vocabulary": "similar_to",
    "similar meaning": "similar_to",
    "antonyms / opposites": "opposite_of",
    "opposites": "opposite_of",
    "opposite / contrast sentences": "contrast_with",
    "contrast with": "contrast_with",
    "confusable words": "confusable_with",
    "confusable / compare with": "confusable_with",
    "negative counterpart": "negative_counterpart",
}


@dataclass(frozen=True)
class RelationBackfillMigration:
    """
    Backfills generic `## Relations` from older human sections.

    Design rules:
    - Non-destructive.
    - Does not remove legacy sections yet.
    - Does not overwrite user-written relation links.
    - Removes `- TODO` only when inserting real links into that relation block.
    - Idempotent.
    - Only processes vocabulary/sentence/grammar notes.
    """

    backfill_version: str = RELATION_BACKFILL_VERSION

    @property
    def name(self) -> str:
        return f"Relation Backfill Migration v{self.backfill_version}"

    def should_process(self, note: VaultNote) -> bool:
        parser = FrontmatterParser()
        document = note.parse(parser)

        if not document.has_frontmatter:
            return False

        item_type = document.get_str("type").strip().lower()

        return item_type in ITEM_RELATION_SECTIONS

    def migrate_note(
        self, note: VaultNote, context: MigrationContext
    ) -> VaultNote | None:
        parser = FrontmatterParser()
        document = note.parse(parser)

        item_type = document.get_str("type").strip().lower()

        if item_type not in ITEM_RELATION_SECTIONS:
            return None

        relation_links = self._collect_legacy_relation_links(document.body)

        if not relation_links:
            return None

        changed = False
        new_metadata = dict(document.metadata)
        new_body = document.body.rstrip()

        current_backfill_version = str(
            new_metadata.get("relation_backfill_version") or ""
        ).strip()

        if current_backfill_version != self.backfill_version:
            new_metadata["relation_backfill_version"] = self.backfill_version
            changed = True

        if not self._has_heading(new_body, "Relations", level=2):
            new_body = self._append_section(
                body=new_body,
                section=self._build_empty_relations_section(
                    ITEM_RELATION_SECTIONS[item_type],
                ),
            )
            changed = True

        updated_body = self._backfill_relations_section(
            body=new_body,
            relation_links=relation_links,
            allowed_relation_types=ITEM_RELATION_SECTIONS[item_type],
        )

        if updated_body != new_body:
            new_body = updated_body
            changed = True

        if not changed:
            return None

        new_document = FrontmatterDocument(
            metadata=new_metadata,
            body=new_body.rstrip() + "\n",
            has_frontmatter=True,
        )

        return note.with_document(new_document, parser=parser)

    def _collect_legacy_relation_links(self, body: str) -> dict[str, list[str]]:
        relation_links: dict[str, list[str]] = {}

        for section_heading, relation_type in LEGACY_SECTION_RELATION_MAP.items():
            section = self._extract_level_2_section_case_insensitive(
                body=body,
                heading=section_heading,
            )

            if not section:
                continue

            wikilinks = self._extract_wikilinks(section)

            if not wikilinks:
                continue

            current_links = relation_links.setdefault(relation_type, [])

            for link in wikilinks:
                if not self._contains_wikilink(current_links, link):
                    current_links.append(link)

        return relation_links

    def _backfill_relations_section(
        self,
        body: str,
        relation_links: dict[str, list[str]],
        allowed_relation_types: Iterable[str],
    ) -> str:
        relations_section = self._extract_section(
            body=body,
            heading="Relations",
            level=2,
        )

        if relations_section == "":
            return body

        allowed = set(allowed_relation_types)
        updated_section_content = relations_section

        for relation_type, links in relation_links.items():
            if relation_type not in allowed:
                continue

            if not links:
                continue

            updated_section_content = self._upsert_relation_block(
                section_content=updated_section_content,
                relation_type=relation_type,
                links=links,
            )

        updated_full_section = "## Relations\n" + updated_section_content.rstrip()
        return self._replace_section(
            body=body,
            heading="Relations",
            level=2,
            replacement=updated_full_section,
        )

    def _upsert_relation_block(
        self,
        section_content: str,
        relation_type: str,
        links: list[str],
    ) -> str:
        blocks = self._split_h3_blocks_with_spans(section_content)

        for heading, block, start, end in blocks:
            if self._block_matches_relation_type(heading, block, relation_type):
                updated_block = self._add_links_to_block(block, links)
                return section_content[:start] + updated_block + section_content[end:]

        new_block = self._build_relation_block(relation_type, links)

        if not section_content.endswith("\n"):
            section_content += "\n"

        return section_content.rstrip() + "\n\n" + new_block + "\n"

    def _add_links_to_block(self, block: str, links: list[str]) -> str:
        lines = block.rstrip().splitlines()
        existing_links = self._extract_wikilinks(block)

        cleaned_lines: list[str] = []

        for line in lines:
            if line.strip() == "- TODO" and links:
                continue

            cleaned_lines.append(line)

        for link in links:
            if not self._contains_wikilink(existing_links, link):
                cleaned_lines.append(f"- {link}")

        return "\n".join(cleaned_lines).rstrip() + "\n"

    def _build_empty_relations_section(self, relation_types: Iterable[str]) -> str:
        lines: list[str] = [
            "## Relations",
            "",
            "Add Obsidian links under the relevant relation type.",
            "Use the `relation_type` line as the machine-readable id.",
            "",
        ]

        for relation_type in relation_types:
            lines.extend(
                [
                    f"### {self._relation_label(relation_type)}",
                    "",
                    f"relation_type: `{relation_type}`",
                    "",
                    "- TODO",
                    "",
                ]
            )

        return "\n".join(lines).rstrip()

    def _build_relation_block(self, relation_type: str, links: list[str]) -> str:
        lines = [
            f"### {self._relation_label(relation_type)}",
            "",
            f"relation_type: `{relation_type}`",
            "",
        ]

        for link in links:
            lines.append(f"- {link}")

        return "\n".join(lines).rstrip()

    def _relation_label(self, relation_type: str) -> str:
        return RELATION_LABELS.get(
            relation_type,
            relation_type.replace("_", " ").title(),
        )

    def _block_matches_relation_type(
        self,
        heading: str,
        block: str,
        relation_type: str,
    ) -> bool:
        relation_type_from_block = self._extract_relation_type_from_block(block)

        if relation_type_from_block == relation_type:
            return True

        heading_key = heading.strip().lower().replace(" ", "_")
        label_key = (
            self._relation_label(relation_type).strip().lower().replace(" ", "_")
        )

        return heading_key in {relation_type, label_key}

    def _extract_relation_type_from_block(self, block: str) -> str:
        match = re.search(
            r"(?im)^relation_type:\s*`?([a-zA-Z0-9_]+)`?\s*$",
            block,
        )

        if not match:
            return ""

        return match.group(1).strip().lower()

    def _split_h3_blocks_with_spans(
        self, section_content: str
    ) -> list[tuple[str, str, int, int]]:
        pattern = r"(?ims)^###\s+(.+?)\s*$\n(.*?)(?=^###\s+|\Z)"
        blocks: list[tuple[str, str, int, int]] = []

        for match in re.finditer(pattern, section_content):
            heading = match.group(1).strip()
            block = match.group(0)
            blocks.append((heading, block, match.start(), match.end()))

        return blocks

    def _extract_wikilinks(self, text: str) -> list[str]:
        links: list[str] = []

        for match in WIKILINK_PATTERN.finditer(text):
            target = match.group(1).strip()
            display = match.group(2).strip() if match.group(2) else ""

            if not target:
                continue

            if target.upper() == "TODO":
                continue

            if display:
                link = f"[[{target}|{display}]]"
            else:
                link = f"[[{target}]]"

            if not self._contains_wikilink(links, link):
                links.append(link)

        return links

    def _contains_wikilink(self, links: list[str], candidate: str) -> bool:
        candidate_key = self._wikilink_key(candidate)

        return any(self._wikilink_key(link) == candidate_key for link in links)

    def _wikilink_key(self, link: str) -> str:
        match = WIKILINK_PATTERN.search(link)

        if not match:
            return link.strip().lower()

        target = match.group(1).strip().replace("\\", "/")

        if target.endswith(".md"):
            target = target[:-3]

        return target.strip("/").lower()

    def _append_section(self, body: str, section: str) -> str:
        body = body.rstrip()
        section = section.strip()

        if not body:
            return section + "\n"

        return body + "\n\n" + section + "\n"

    def _has_heading(self, body: str, heading: str, level: int) -> bool:
        hashes = "#" * level
        pattern = rf"(?im)^{re.escape(hashes)}\s+{re.escape(heading)}\s*$"
        return re.search(pattern, body) is not None

    def _extract_level_2_section_case_insensitive(self, body: str, heading: str) -> str:
        pattern = rf"(?ims)^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)"
        match = re.search(pattern, body, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL)

        if not match:
            return ""

        return match.group(1).strip()

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
