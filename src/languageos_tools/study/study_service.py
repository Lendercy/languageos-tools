from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

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
    limit: int = 100


@dataclass(frozen=True)
class StudyRelation:
    direction: str
    relation_type: str
    source_key: str
    target_key: str


@dataclass(frozen=True)
class StudyCard:
    card_id: str
    item_key: str
    note_type: str
    language: str
    front: str
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


class MarkdownSectionExtractor:
    """
    Extracts simple Markdown sections by heading title.

    Supports headings like:
    ## Meaning
    ### Meaning
    ## Explanation
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
    - vault Markdown notes for study content;
    - SQLite relation index for connected relations when available.
    """

    DEFAULT_LEARNING_TYPES = frozenset(
        {
            "vocabulary",
            "sentence",
            "grammar",
        }
    )

    def __init__(
        self,
        *,
        vault_path: Path,
        db_path: Path | None = None,
        frontmatter_reader: MarkdownFrontmatterReader | None = None,
        item_key_extractor: ItemKeyExtractor | None = None,
        section_extractor: MarkdownSectionExtractor | None = None,
    ) -> None:
        self.vault_path = vault_path
        self.db_path = db_path
        self.frontmatter_reader = frontmatter_reader or MarkdownFrontmatterReader()
        self.item_key_extractor = item_key_extractor or ItemKeyExtractor()
        self.section_extractor = section_extractor or MarkdownSectionExtractor()

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
                content=content,
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
        content: str,
        item_key: ItemKey,
        frontmatter: Mapping[str, object],
        sections: Mapping[str, str],
        relations: tuple[StudyRelation, ...],
    ) -> StudyCard:
        note_type = item_key.item_type.strip().casefold()

        front = item_key.normalized

        back = self._first_non_empty(
            frontmatter.get("meaning"),
            frontmatter.get("explanation"),
            sections.get("meaning"),
            sections.get("explanation"),
            sections.get("definition"),
            sections.get("notes"),
        )

        if back is None:
            back = "No Meaning/Explanation found yet."

        examples = self._first_non_empty(
            sections.get("examples"),
            sections.get("example"),
        ) or ""

        notes = self._first_non_empty(
            sections.get("notes"),
            sections.get("usage"),
            sections.get("grammar_notes"),
        ) or ""

        return StudyCard(
            card_id=item_key.render(),
            item_key=item_key.render(),
            note_type=note_type,
            language=item_key.language.strip().casefold(),
            front=front,
            back=str(back).strip(),
            examples=examples.strip(),
            notes=notes.strip(),
            file_path=str(path),
            relations=relations,
        )

    def _load_relation_map(self) -> dict[str, tuple[StudyRelation, ...]]:
        if self.db_path is None or not self.db_path.exists():
            return {}

        try:
            records = DatabaseRelationSource(self.db_path).load_relations()
        except Exception:
            return {}

        relation_map: dict[str, list[StudyRelation]] = defaultdict(list)

        for record in records:
            relation_map[record.source_key].append(
                self._to_study_relation(record, direction="outgoing")
            )
            relation_map[record.target_key].append(
                self._to_study_relation(record, direction="incoming")
            )

        return {
            item_key: tuple(relations)
            for item_key, relations in relation_map.items()
        }

    def _to_study_relation(
        self,
        record: RelationRecord,
        *,
        direction: str,
    ) -> StudyRelation:
        return StudyRelation(
            direction=direction,
            relation_type=record.relation_type,
            source_key=record.source_key,
            target_key=record.target_key,
        )

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
                card.back,
                card.examples,
                card.notes,
                card.file_path,
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