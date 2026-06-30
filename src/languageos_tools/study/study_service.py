from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from languageos_tools.core.normalization import (
    ItemKey,
    ItemKeyExtractor,
    MarkdownFrontmatterReader,
)
from languageos_tools.relations.integrity_audit import (
    DatabaseRelationSource,
    RelationRecord,
)


@dataclass(frozen=True)
class StudyFilter:
    language: str = "all"
    note_type: str = "all"
    query: str = ""
    limit: int = 200


@dataclass(frozen=True)
class StudyRelation:
    direction: str
    relation_type: str
    source_key: str
    target_key: str
    display_label: str
    display_item: str


@dataclass(frozen=True)
class StudyCard:
    card_id: str
    item_key: str
    note_type: str
    language: str
    front: str
    subtitle: str
    back: str
    examples: str
    notes: str
    file_path: str
    relations: tuple[StudyRelation, ...]


@dataclass(frozen=True)
class StudyDeckSummary:
    total_cards: int
    cards_by_type: Mapping[str, int]
    cards_by_language: Mapping[str, int]


@dataclass(frozen=True)
class StudyDeck:
    cards: tuple[StudyCard, ...]
    summary: StudyDeckSummary


class ObsidianDisplayCleaner:
    """
    Converts Obsidian-flavored Markdown into learner-friendly display Markdown.

    This is presentation cleanup only. It does not mutate notes.
    """

    WIKILINK_PATTERN = re.compile(r"!?\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
    HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

    def clean_markdown(self, text: str) -> str:
        value = text.strip()
        value = self._strip_frontmatter(value)
        value = self._convert_wikilinks(value)
        value = self._demote_headings(value)
        value = self._collapse_blank_lines(value)
        return value.strip()

    def clean_inline(self, text: str) -> str:
        value = self._convert_wikilinks(text.strip())
        value = re.sub(r"`([^`]+)`", r"\1", value)
        value = re.sub(r"\s+", " ", value).strip()
        return value

    def display_from_item_key(self, item_key: str) -> str:
        parts = item_key.split("|", maxsplit=2)
        if len(parts) == 3:
            return parts[2]
        return item_key

    def _strip_frontmatter(self, text: str) -> str:
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            return text

        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                return "\n".join(lines[index + 1 :])

        return text

    def _convert_wikilinks(self, text: str) -> str:
        def replace(match: re.Match[str]) -> str:
            path = match.group(1).strip()
            alias = match.group(2)

            if alias:
                return alias.strip()

            filename = path.replace("\\", "/").split("/")[-1]
            return filename.strip()

        return self.WIKILINK_PATTERN.sub(replace, text)

    def _demote_headings(self, text: str) -> str:
        lines: list[str] = []

        for line in text.splitlines():
            match = self.HEADING_PATTERN.match(line.strip())
            if not match:
                lines.append(line)
                continue

            title = match.group(2).strip()
            lines.append(f"**{title}**")

        return "\n".join(lines)

    def _collapse_blank_lines(self, text: str) -> str:
        return re.sub(r"\n{3,}", "\n\n", text)


class MarkdownSectionExtractor:
    """
    Extract simple Markdown sections by heading title.

    Supports:
    ## Meaning
    ### Explanation
    ## Examples
    """

    HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

    def extract_sections(self, markdown: str) -> dict[str, str]:
        body = self._strip_frontmatter(markdown)
        lines = body.splitlines()

        sections: dict[str, list[str]] = {}
        current_key: str | None = None

        for line in lines:
            match = self.HEADING_PATTERN.match(line.strip())

            if match:
                raw_title = match.group(2).strip().strip("#").strip()
                current_key = self._normalize_heading(raw_title)
                sections.setdefault(current_key, [])
                continue

            if current_key is not None:
                sections[current_key].append(line)

        return {
            key: "\n".join(value).strip()
            for key, value in sections.items()
            if "\n".join(value).strip()
        }

    def _strip_frontmatter(self, markdown: str) -> str:
        lines = markdown.splitlines()

        if not lines or lines[0].strip() != "---":
            return markdown

        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                return "\n".join(lines[index + 1 :])

        return markdown

    def _normalize_heading(self, heading: str) -> str:
        return re.sub(r"\s+", "_", heading.strip().casefold())


class StudyService:
    """
    Builds learner-facing study cards from the Obsidian vault.

    Source of truth:
    - vault Markdown notes for content;
    - SQLite relation index for connected relations when available.
    """

    DEFAULT_LEARNING_TYPES = frozenset(
        {
            "vocabulary",
            "sentence",
            "grammar",
        }
    )

    RELATION_LABELS = {
        "contains_vocabulary": "Contains vocabulary",
        "uses_grammar": "Uses grammar",
        "example_of": "Example of",
        "related_to": "Related to",
        "contrasts_with": "Contrasts with",
        "derived_from": "Derived from",
    }

    def __init__(
        self,
        *,
        vault_path: Path,
        db_path: Path | None = None,
        frontmatter_reader: MarkdownFrontmatterReader | None = None,
        item_key_extractor: ItemKeyExtractor | None = None,
        section_extractor: MarkdownSectionExtractor | None = None,
        display_cleaner: ObsidianDisplayCleaner | None = None,
    ) -> None:
        self.vault_path = vault_path
        self.db_path = db_path
        self.frontmatter_reader = frontmatter_reader or MarkdownFrontmatterReader()
        self.item_key_extractor = item_key_extractor or ItemKeyExtractor()
        self.section_extractor = section_extractor or MarkdownSectionExtractor()
        self.display_cleaner = display_cleaner or ObsidianDisplayCleaner()

    def load_deck(self, study_filter: StudyFilter) -> StudyDeck:
        if not self.vault_path.exists():
            raise FileNotFoundError(f"Vault path does not exist: {self.vault_path}")

        relation_map = self._load_relation_map()
        cards: list[StudyCard] = []

        for path in sorted(self.vault_path.rglob("*.md")):
            content = path.read_text(encoding="utf-8")
            frontmatter = self.frontmatter_reader.read_frontmatter(path)
            item_key = self.item_key_extractor.extract(frontmatter)

            if item_key is None:
                continue

            note_type = item_key.item_type.strip().casefold()
            language = item_key.language.strip().casefold()

            if note_type not in self.DEFAULT_LEARNING_TYPES:
                continue

            if study_filter.note_type != "all" and note_type != study_filter.note_type:
                continue

            if study_filter.language != "all" and language != study_filter.language:
                continue

            sections = self.section_extractor.extract_sections(content)

            card = self._build_card(
                path=path,
                item_key=item_key,
                frontmatter=frontmatter,
                sections=sections,
                relations=relation_map.get(item_key.render(), ()),
            )

            if not self._matches_query(card, study_filter.query):
                continue

            cards.append(card)

            if len(cards) >= study_filter.limit:
                break

        return StudyDeck(
            cards=tuple(cards),
            summary=self._summarize(cards),
        )

    def _build_card(
        self,
        *,
        path: Path,
        item_key: ItemKey,
        frontmatter: Mapping[str, Any],
        sections: Mapping[str, str],
        relations: tuple[StudyRelation, ...],
    ) -> StudyCard:
        note_type = item_key.item_type.strip().casefold()

        front = self._first_non_empty(
            frontmatter.get("term"),
            frontmatter.get("sentence"),
            frontmatter.get("title"),
            frontmatter.get("name"),
            item_key.normalized,
        )
        if front is None:
            front = item_key.normalized

        subtitle = self._build_subtitle(note_type=note_type, item_key=item_key)

        back = self._first_non_empty(
            frontmatter.get("meaning"),
            frontmatter.get("explanation"),
            sections.get("meaning"),
            sections.get("explanation"),
            sections.get("definition"),
            sections.get("pattern"),
            sections.get("notes"),
        )

        if back is None:
            back = "No Meaning/Explanation found yet."

        examples = self._first_non_empty(
            sections.get("examples"),
            sections.get("example"),
            sections.get("sentences"),
        ) or ""

        notes = self._first_non_empty(
            sections.get("notes"),
            sections.get("usage"),
            sections.get("grammar_notes"),
            sections.get("pattern"),
        ) or ""

        return StudyCard(
            card_id=item_key.render(),
            item_key=item_key.render(),
            note_type=note_type,
            language=item_key.language.strip().casefold(),
            front=self.display_cleaner.clean_inline(str(front)),
            subtitle=subtitle,
            back=self.display_cleaner.clean_markdown(str(back)),
            examples=self.display_cleaner.clean_markdown(str(examples)),
            notes=self.display_cleaner.clean_markdown(str(notes)),
            file_path=str(path),
            relations=relations,
        )

    def _build_subtitle(self, *, note_type: str, item_key: ItemKey) -> str:
        if note_type == "vocabulary":
            return "Vocabulary item"
        if note_type == "sentence":
            return "Sentence card"
        if note_type == "grammar":
            return "Grammar concept"
        return item_key.render()

    def _load_relation_map(self) -> dict[str, tuple[StudyRelation, ...]]:
        if self.db_path is None or not self.db_path.exists():
            return {}

        try:
            records = DatabaseRelationSource(self.db_path).load_relations()
        except Exception:
            return {}

        relation_map: dict[str, list[StudyRelation]] = defaultdict(list)

        for record in records:
            source_key = self._stringify_relation_key(record.source_key)
            target_key = self._stringify_relation_key(record.target_key)
            relation_type = self._stringify_relation_type(record.relation_type)

            outgoing = self._to_study_relation(
                direction="outgoing",
                relation_type=relation_type,
                source_key=source_key,
                target_key=target_key,
            )
            incoming = self._to_study_relation(
                direction="incoming",
                relation_type=relation_type,
                source_key=source_key,
                target_key=target_key,
            )

            relation_map[source_key].append(outgoing)
            relation_map[target_key].append(incoming)

        return {
            item_key: tuple(relations)
            for item_key, relations in relation_map.items()
        }

    def _to_study_relation(
        self,
        *,
        direction: str,
        relation_type: str,
        source_key: str,
        target_key: str,
    ) -> StudyRelation:
        if direction == "outgoing":
            display_item = self.display_cleaner.display_from_item_key(target_key)
        else:
            display_item = self.display_cleaner.display_from_item_key(source_key)

        return StudyRelation(
            direction=direction,
            relation_type=relation_type,
            source_key=source_key,
            target_key=target_key,
            display_label=self._relation_label(relation_type),
            display_item=display_item,
        )

    def _relation_label(self, relation_type: str) -> str:
        clean = relation_type.strip().casefold()
        if clean in self.RELATION_LABELS:
            return self.RELATION_LABELS[clean]
        return clean.replace("_", " ").title()

    def _stringify_relation_key(self, value: object) -> str:
        if hasattr(value, "render"):
            return str(value.render())
        return str(value)

    def _stringify_relation_type(self, value: object) -> str:
        if hasattr(value, "value"):
            return str(value.value)
        return str(value)

    def _matches_query(self, card: StudyCard, query: str) -> bool:
        clean_query = query.strip().casefold()

        if not clean_query:
            return True

        searchable = "\n".join(
            [
                card.item_key,
                card.note_type,
                card.language,
                card.front,
                card.subtitle,
                card.back,
                card.examples,
                card.notes,
                card.file_path,
                *[
                    f"{relation.display_label} {relation.display_item}"
                    for relation in card.relations
                ],
            ]
        ).casefold()

        return clean_query in searchable

    def _first_non_empty(self, *values: object | None) -> str | None:
        for value in values:
            if value is None:
                continue

            text = str(value).strip()
            if text:
                return text

        return None

    def _summarize(self, cards: Sequence[StudyCard]) -> StudyDeckSummary:
        cards_by_type: dict[str, int] = defaultdict(int)
        cards_by_language: dict[str, int] = defaultdict(int)

        for card in cards:
            cards_by_type[card.note_type] += 1
            cards_by_language[card.language] += 1

        return StudyDeckSummary(
            total_cards=len(cards),
            cards_by_type=dict(cards_by_type),
            cards_by_language=dict(cards_by_language),
        )