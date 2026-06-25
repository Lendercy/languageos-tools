from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from languageos_tools.core.enums import RelationType
from languageos_tools.core.models import LanguageItemKey
from languageos_tools.obsidian.note import VaultNote
from languageos_tools.relations.service import RelationCandidate, RelationService


WIKILINK_PATTERN = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]")

LEGACY_SECTION_RELATION_MAP: dict[str, RelationType] = {
    "contains vocabulary": RelationType.CONTAINS_VOCABULARY,
    "grammar / pattern": RelationType.USES_GRAMMAR,
    "related grammar": RelationType.USES_GRAMMAR,
    "similar sentences": RelationType.SIMILAR_TO,
    "similar vocabulary": RelationType.SIMILAR_TO,
    "similar meaning": RelationType.SIMILAR_TO,
    "antonyms / opposites": RelationType.OPPOSITE_OF,
    "opposites": RelationType.OPPOSITE_OF,
    "opposite / contrast sentences": RelationType.CONTRAST_WITH,
    "contrast with": RelationType.CONTRAST_WITH,
    "confusable words": RelationType.CONFUSABLE_WITH,
    "confusable / compare with": RelationType.CONFUSABLE_WITH,
    "negative counterpart": RelationType.NEGATIVE_COUNTERPART,
}


@dataclass(frozen=True)
class ParsedWikiLink:
    target: str
    display: str

    @property
    def normalized_target(self) -> str:
        target = self.target.strip().replace("\\", "/")

        if target.endswith(".md"):
            target = target[:-3]

        return target.strip("/")


@dataclass(frozen=True)
class ParsedRelation:
    source_key: LanguageItemKey
    target_key: LanguageItemKey
    relation_type: RelationType
    confidence: float
    evidence: str
    source_path: str
    target_path: str


@dataclass(frozen=True)
class RelationParseContext:
    item_key_by_obsidian_path: dict[str, LanguageItemKey]
    obsidian_path_by_item_key: dict[str, str]
    item_key_by_title: dict[str, list[LanguageItemKey]]
    obsidian_path_by_title_key: dict[str, list[str]]


class RelationMarkdownParser:
    """
    Parses relation links from Obsidian notes.

    Supported sources:
    1. Generic `## Relations` section:
       ### Uses Grammar
       relation_type: `uses_grammar`
       - [[Grammar/German/Contrast connectors|Contrast connectors]]

    2. Legacy sections:
       ## Contains Vocabulary
       ## Grammar / Pattern
       ## Related Grammar
       ## Similar Sentences
       etc.

    This lets older notes keep working while the system moves toward the generic
    relation taxonomy.
    """

    def __init__(self, relation_service: RelationService) -> None:
        self._relation_service = relation_service

    def parse_note(
        self,
        note: VaultNote,
        context: RelationParseContext,
    ) -> list[ParsedRelation]:
        document = note.parse()

        if not document.has_frontmatter:
            return []

        source_key = self._source_key_from_note(note)

        if source_key is None:
            return []

        candidates: list[RelationCandidate] = []
        candidates.extend(
            self._parse_generic_relations_section(
                note=note,
                source_key=source_key,
                context=context,
            )
        )
        candidates.extend(
            self._parse_legacy_relation_sections(
                note=note,
                source_key=source_key,
                context=context,
            )
        )

        parsed_relations: list[ParsedRelation] = []

        for candidate in candidates:
            try:
                relation = self._relation_service.create_relation(candidate)
            except ValueError:
                continue

            source_path = context.obsidian_path_by_item_key.get(
                relation.source_key.as_string(),
                note.obsidian_path,
            )
            target_path = context.obsidian_path_by_item_key.get(
                relation.target_key.as_string(),
                "",
            )

            parsed_relations.append(
                ParsedRelation(
                    source_key=relation.source_key,
                    target_key=relation.target_key,
                    relation_type=relation.relation_type,
                    confidence=relation.confidence,
                    evidence=relation.evidence,
                    source_path=source_path,
                    target_path=target_path,
                )
            )

        return self._deduplicate(parsed_relations)

    def _parse_generic_relations_section(
        self,
        note: VaultNote,
        source_key: LanguageItemKey,
        context: RelationParseContext,
    ) -> list[RelationCandidate]:
        body = note.body()
        section = self._extract_level_2_section(body, "Relations")

        if not section:
            return []

        h3_blocks = self._split_h3_blocks(section)
        candidates: list[RelationCandidate] = []

        for heading, block in h3_blocks:
            relation_type = self._extract_relation_type_from_block(block)

            if relation_type is None:
                relation_type = self._relation_type_from_heading(heading)

            if relation_type is None:
                continue

            links = self._extract_wikilinks(block)

            for link in links:
                target_key = self._resolve_link_to_item_key(link, context)

                if target_key is None:
                    continue

                candidates.append(
                    RelationCandidate(
                        source_key=source_key,
                        target_key=target_key,
                        relation_type=relation_type,
                        confidence=1.0,
                        evidence=f"generic_relations_section:{heading}",
                        created_by="relation_parser",
                    )
                )

        return candidates

    def _parse_legacy_relation_sections(
        self,
        note: VaultNote,
        source_key: LanguageItemKey,
        context: RelationParseContext,
    ) -> list[RelationCandidate]:
        body = note.body()
        candidates: list[RelationCandidate] = []

        for section_heading, relation_type in LEGACY_SECTION_RELATION_MAP.items():
            section = self._extract_level_2_section_case_insensitive(
                body,
                section_heading,
            )

            if not section:
                continue

            links = self._extract_wikilinks(section)

            for link in links:
                target_key = self._resolve_link_to_item_key(link, context)

                if target_key is None:
                    continue

                candidates.append(
                    RelationCandidate(
                        source_key=source_key,
                        target_key=target_key,
                        relation_type=relation_type,
                        confidence=0.95,
                        evidence=f"legacy_section:{section_heading}",
                        created_by="relation_parser",
                    )
                )

        return candidates

    def _source_key_from_note(self, note: VaultNote) -> LanguageItemKey | None:
        document = note.parse()

        item_type = document.get_str("type").strip().lower()

        if not item_type:
            return None

        language = document.get_str("language", "unknown").strip().lower()
        normalized = document.get_str("normalized").strip().lower()

        if not normalized:
            normalized = self._normalize_text(
                document.get_str("term")
                or document.get_str("sentence")
                or document.get_str("title")
                or note.title
            )

        if not normalized:
            return None

        return LanguageItemKey(
            item_type=item_type,
            language=language or "unknown",
            normalized=normalized,
        )

    def _extract_level_2_section(self, body: str, heading: str) -> str:
        pattern = rf"(?ims)^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)"
        match = re.search(pattern, body)

        if not match:
            return ""

        return match.group(1).strip()

    def _extract_level_2_section_case_insensitive(self, body: str, heading: str) -> str:
        pattern = rf"(?ims)^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)"
        match = re.search(pattern, body, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL)

        if not match:
            return ""

        return match.group(1).strip()

    def _split_h3_blocks(self, section: str) -> list[tuple[str, str]]:
        pattern = r"(?ims)^###\s+(.+?)\s*$\n(.*?)(?=^###\s+|\Z)"
        blocks: list[tuple[str, str]] = []

        for match in re.finditer(pattern, section):
            heading = match.group(1).strip()
            block = match.group(2).strip()
            blocks.append((heading, block))

        return blocks

    def _extract_relation_type_from_block(self, block: str) -> RelationType | None:
        match = re.search(
            r"(?im)^relation_type:\s*`?([a-zA-Z0-9_]+)`?\s*$",
            block,
        )

        if not match:
            return None

        relation_id = match.group(1).strip().lower()

        return self._relation_type_from_id(relation_id)

    def _relation_type_from_heading(self, heading: str) -> RelationType | None:
        relation_id = self._normalize_text(heading).replace(" ", "_")

        return self._relation_type_from_id(relation_id)

    def _relation_type_from_id(self, relation_id: str) -> RelationType | None:
        for relation_type in RelationType:
            if relation_type.value == relation_id:
                return relation_type

        return None

    def _extract_wikilinks(self, text: str) -> list[ParsedWikiLink]:
        links: list[ParsedWikiLink] = []

        for match in WIKILINK_PATTERN.finditer(text):
            target = match.group(1).strip()
            display = match.group(2).strip() if match.group(2) else Path(target).stem

            if not target or target.upper() == "TODO":
                continue

            links.append(
                ParsedWikiLink(
                    target=target,
                    display=display,
                )
            )

        return links

    def _resolve_link_to_item_key(
        self,
        link: ParsedWikiLink,
        context: RelationParseContext,
    ) -> LanguageItemKey | None:
        path_key = self._normalize_obsidian_path(link.normalized_target)

        if path_key in context.item_key_by_obsidian_path:
            return context.item_key_by_obsidian_path[path_key]

        title_key = self._normalize_text(Path(link.normalized_target).stem)
        title_matches = context.item_key_by_title.get(title_key, [])

        if len(title_matches) == 1:
            return title_matches[0]

        return None

    def _normalize_obsidian_path(self, path: str) -> str:
        path = path.strip().replace("\\", "/")

        if path.endswith(".md"):
            path = path[:-3]

        return path.strip("/").lower()

    def _normalize_text(self, text: str) -> str:
        text = str(text or "").strip().lower()
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"[“”\"'`]", "", text)
        text = re.sub(r"[.!?。！？]+$", "", text)
        return text.strip()

    def _deduplicate(self, relations: Iterable[ParsedRelation]) -> list[ParsedRelation]:
        seen: set[tuple[str, str, str]] = set()
        result: list[ParsedRelation] = []

        for relation in relations:
            key = (
                relation.source_key.as_string(),
                relation.target_key.as_string(),
                relation.relation_type.value,
            )

            if key in seen:
                continue

            seen.add(key)
            result.append(relation)

        return result


def build_relation_parse_context(notes: Iterable[VaultNote]) -> RelationParseContext:
    item_key_by_obsidian_path: dict[str, LanguageItemKey] = {}
    obsidian_path_by_item_key: dict[str, str] = {}
    item_key_by_title: dict[str, list[LanguageItemKey]] = {}
    obsidian_path_by_title_key: dict[str, list[str]] = {}

    for note in notes:
        document = note.parse()

        if not document.has_frontmatter:
            continue

        item_type = document.get_str("type").strip().lower()

        if not item_type:
            continue

        language = document.get_str("language", "unknown").strip().lower()
        normalized = document.get_str("normalized").strip().lower()

        if not normalized:
            normalized = _normalize_text(
                document.get_str("term")
                or document.get_str("sentence")
                or document.get_str("title")
                or note.title
            )

        if not normalized:
            continue

        key = LanguageItemKey(
            item_type=item_type,
            language=language or "unknown",
            normalized=normalized,
        )

        obsidian_path_key = note.obsidian_path.lower()
        title_key = _normalize_text(note.title)

        item_key_by_obsidian_path[obsidian_path_key] = key
        obsidian_path_by_item_key[key.as_string()] = note.obsidian_path

        item_key_by_title.setdefault(title_key, []).append(key)
        obsidian_path_by_title_key.setdefault(title_key, []).append(note.obsidian_path)

    return RelationParseContext(
        item_key_by_obsidian_path=item_key_by_obsidian_path,
        obsidian_path_by_item_key=obsidian_path_by_item_key,
        item_key_by_title=item_key_by_title,
        obsidian_path_by_title_key=obsidian_path_by_title_key,
    )


def _normalize_text(text: str) -> str:
    text = str(text or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[“”\"'`]", "", text)
    text = re.sub(r"[.!?。！？]+$", "", text)
    return text.strip()