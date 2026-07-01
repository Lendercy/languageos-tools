from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from languageos_tools.core.normalization import ItemKey
from languageos_tools.relations.integrity_audit import DatabaseRelationSource

logger = logging.getLogger(__name__)


class MatchKind(str, Enum):
    EXACT_KEY = "exact_key"
    EXACT_NORMALIZED = "exact_normalized"
    PREFIX_NORMALIZED = "prefix_normalized"
    CONTAINS_NORMALIZED = "contains_normalized"
    CONTAINS_TEXT = "contains_text"


@dataclass(frozen=True)
class LookupItem:
    item_key: str
    item_type: str
    language: str
    normalized: str
    source_table: str
    rowid: int | None = None
    title: str | None = None
    file_path: str | None = None
    text_preview: str | None = None


@dataclass(frozen=True)
class LookupMatch:
    item: LookupItem
    match_kind: MatchKind
    score: float


@dataclass(frozen=True)
class ConnectedRelation:
    direction: str
    source_key: str
    relation_type: str
    target_key: str
    source_table: str
    rowid: int | None = None


@dataclass(frozen=True)
class LookupReport:
    query: str
    db_path: str
    matches: tuple[LookupMatch, ...]
    connected_relations: Mapping[str, tuple[ConnectedRelation, ...]]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "db_path": self.db_path,
            "matches": [
                {
                    "match_kind": match.match_kind.value,
                    "score": match.score,
                    "item": dataclasses.asdict(match.item),
                }
                for match in self.matches
            ],
            "connected_relations": {
                item_key: [dataclasses.asdict(relation) for relation in relations]
                for item_key, relations in self.connected_relations.items()
            },
        }

    def write_json(self, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(self.to_json_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class DatabaseLookupItemSource:
    """
    Loads indexable LanguageOS items from SQLite.

    This is schema-tolerant because the DB layer is still evolving.
    It supports either:
    - explicit item_key/key/id columns containing item_type|language|normalized;
    - composed columns type/language/normalized.
    """

    KEY_COLUMNS = ("item_key", "key", "id")
    TYPE_COLUMNS = ("type", "item_type", "note_type")
    LANGUAGE_COLUMNS = ("language", "lang")
    NORMALIZED_COLUMNS = ("normalized", "normalized_text", "canonical")
    TITLE_COLUMNS = ("title", "name", "note_title")
    FILE_PATH_COLUMNS = ("file_path", "path", "note_path", "source_file")
    TEXT_COLUMNS = ("body", "content", "text", "snippet", "raw_text")

    PREFERRED_TABLES = (
        "items",
        "language_items",
        "notes",
        "documents",
        "fts_documents",
    )

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def load_items(self) -> tuple[LookupItem, ...]:
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database path does not exist: {self.db_path}")

        items: list[LookupItem] = []

        with sqlite3.connect(str(self.db_path)) as connection:
            connection.row_factory = sqlite3.Row

            for table_name in self._ordered_tables(connection):
                columns = self._table_columns(connection, table_name)
                table_items = self._load_table_items(
                    connection=connection,
                    table_name=table_name,
                    columns=columns,
                )
                items.extend(table_items)

        return self._dedupe_items(items)

    def _ordered_tables(self, connection: sqlite3.Connection) -> tuple[str, ...]:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            ORDER BY name
            """
        ).fetchall()

        table_names = tuple(
            str(row["name"])
            for row in rows
            if not str(row["name"]).startswith("sqlite_")
        )

        preferred = [
            table_name
            for table_name in self.PREFERRED_TABLES
            if table_name in table_names
        ]
        fallback = [
            table_name for table_name in table_names if table_name not in preferred
        ]

        return tuple(preferred + fallback)

    def _table_columns(
        self,
        connection: sqlite3.Connection,
        table_name: str,
    ) -> set[str]:
        rows = connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        return {str(row["name"]) for row in rows}

    def _load_table_items(
        self,
        *,
        connection: sqlite3.Connection,
        table_name: str,
        columns: set[str],
    ) -> tuple[LookupItem, ...]:
        explicit_key_col = self._first_existing(columns, self.KEY_COLUMNS)
        type_col = self._first_existing(columns, self.TYPE_COLUMNS)
        language_col = self._first_existing(columns, self.LANGUAGE_COLUMNS)
        normalized_col = self._first_existing(columns, self.NORMALIZED_COLUMNS)
        title_col = self._first_existing(columns, self.TITLE_COLUMNS)
        file_path_col = self._first_existing(columns, self.FILE_PATH_COLUMNS)
        text_col = self._first_existing(columns, self.TEXT_COLUMNS)

        if explicit_key_col is None and not (
            type_col and language_col and normalized_col
        ):
            return ()

        select_parts = ["rowid AS __rowid__"]

        aliases: dict[str, str] = {}
        for alias, col in {
            "explicit_key": explicit_key_col,
            "item_type": type_col,
            "language": language_col,
            "normalized": normalized_col,
            "title": title_col,
            "file_path": file_path_col,
            "text_preview": text_col,
        }.items():
            if col is not None:
                select_parts.append(f'"{col}" AS "{alias}"')
                aliases[alias] = col
            else:
                select_parts.append(f'NULL AS "{alias}"')

        query = f'SELECT {", ".join(select_parts)} FROM "{table_name}"'

        items: list[LookupItem] = []
        for row in connection.execute(query):
            item = self._row_to_item(row=row, table_name=table_name)
            if item is not None:
                items.append(item)

        return tuple(items)

    def _row_to_item(
        self,
        *,
        row: sqlite3.Row,
        table_name: str,
    ) -> LookupItem | None:
        explicit_key = self._clean_optional(row["explicit_key"])

        if explicit_key:
            try:
                parsed_key = ItemKey.parse(explicit_key)
            except ValueError:
                parsed_key = None

            if parsed_key is not None:
                return LookupItem(
                    item_key=parsed_key.render(),
                    item_type=parsed_key.item_type,
                    language=parsed_key.language,
                    normalized=parsed_key.normalized,
                    source_table=table_name,
                    rowid=int(row["__rowid__"]),
                    title=self._clean_optional(row["title"]),
                    file_path=self._clean_optional(row["file_path"]),
                    text_preview=self._preview(row["text_preview"]),
                )

        item_type = self._clean_optional(row["item_type"])
        language = self._clean_optional(row["language"])
        normalized = self._clean_optional(row["normalized"])

        if not item_type or not language or not normalized:
            return None

        item_key = ItemKey(
            item_type=item_type,
            language=language,
            normalized=normalized,
        )

        return LookupItem(
            item_key=item_key.render(),
            item_type=item_type.strip().casefold(),
            language=language.strip().casefold(),
            normalized=normalized.strip(),
            source_table=table_name,
            rowid=int(row["__rowid__"]),
            title=self._clean_optional(row["title"]),
            file_path=self._clean_optional(row["file_path"]),
            text_preview=self._preview(row["text_preview"]),
        )

    def _first_existing(
        self,
        columns: set[str],
        candidates: Sequence[str],
    ) -> str | None:
        for candidate in candidates:
            if candidate in columns:
                return candidate
        return None

    def _clean_optional(self, value: Any) -> str | None:
        if value is None:
            return None

        text = str(value).strip()
        return text or None

    def _preview(self, value: Any, *, limit: int = 180) -> str | None:
        text = self._clean_optional(value)
        if text is None:
            return None

        normalized = " ".join(text.split())
        if len(normalized) <= limit:
            return normalized

        return normalized[: limit - 3] + "..."

    def _dedupe_items(self, items: Sequence[LookupItem]) -> tuple[LookupItem, ...]:
        by_key: dict[str, LookupItem] = {}

        for item in items:
            existing = by_key.get(item.item_key)
            if existing is None:
                by_key[item.item_key] = item
                continue

            by_key[item.item_key] = self._prefer_richer_item(existing, item)

        return tuple(by_key[key] for key in sorted(by_key))

    def _prefer_richer_item(self, left: LookupItem, right: LookupItem) -> LookupItem:
        left_score = self._richness_score(left)
        right_score = self._richness_score(right)

        if right_score > left_score:
            return right

        return left

    def _richness_score(self, item: LookupItem) -> int:
        return sum(
            1 for value in (item.title, item.file_path, item.text_preview) if value
        )


class LookupService:
    def __init__(self, *, db_path: Path) -> None:
        self.db_path = db_path
        self.item_source = DatabaseLookupItemSource(db_path)
        self.relation_source = DatabaseRelationSource(db_path)

    def lookup(
        self,
        *,
        query: str,
        item_type: str | None = None,
        language: str | None = None,
        limit: int = 20,
        with_relations: bool = False,
    ) -> LookupReport:
        clean_query = query.strip()
        if not clean_query:
            raise ValueError("Lookup query cannot be empty.")

        items = self.item_source.load_items()
        matches = self._match_items(
            items=items,
            query=clean_query,
            item_type=item_type,
            language=language,
            limit=limit,
        )

        connected_relations: dict[str, tuple[ConnectedRelation, ...]] = {}
        if with_relations and matches:
            connected_relations = self._load_connected_relations(
                item_keys=tuple(match.item.item_key for match in matches)
            )

        return LookupReport(
            query=clean_query,
            db_path=str(self.db_path),
            matches=tuple(matches),
            connected_relations=connected_relations,
        )

    def _match_items(
        self,
        *,
        items: Sequence[LookupItem],
        query: str,
        item_type: str | None,
        language: str | None,
        limit: int,
    ) -> list[LookupMatch]:
        query_folded = query.casefold()
        normalized_type = item_type.strip().casefold() if item_type else None
        normalized_language = language.strip().casefold() if language else None

        matches: list[LookupMatch] = []

        for item in items:
            if normalized_type and item.item_type.casefold() != normalized_type:
                continue

            if normalized_language and item.language.casefold() != normalized_language:
                continue

            match = self._score_item(item=item, query_folded=query_folded)
            if match is not None:
                matches.append(match)

        matches.sort(
            key=lambda match: (
                -match.score,
                match.item.item_type,
                match.item.language,
                match.item.normalized,
            )
        )

        return matches[:limit]

    def _score_item(
        self,
        *,
        item: LookupItem,
        query_folded: str,
    ) -> LookupMatch | None:
        item_key = item.item_key.casefold()
        normalized = item.normalized.casefold()
        title = (item.title or "").casefold()
        text_preview = (item.text_preview or "").casefold()

        if query_folded == item_key:
            return LookupMatch(
                item=item,
                match_kind=MatchKind.EXACT_KEY,
                score=100.0,
            )

        if query_folded == normalized:
            return LookupMatch(
                item=item,
                match_kind=MatchKind.EXACT_NORMALIZED,
                score=90.0,
            )

        if normalized.startswith(query_folded):
            return LookupMatch(
                item=item,
                match_kind=MatchKind.PREFIX_NORMALIZED,
                score=75.0,
            )

        if query_folded in normalized:
            return LookupMatch(
                item=item,
                match_kind=MatchKind.CONTAINS_NORMALIZED,
                score=60.0,
            )

        if query_folded in title or query_folded in text_preview:
            return LookupMatch(
                item=item,
                match_kind=MatchKind.CONTAINS_TEXT,
                score=40.0,
            )

        return None

    def _load_connected_relations(
        self,
        *,
        item_keys: Sequence[str],
    ) -> dict[str, tuple[ConnectedRelation, ...]]:
        item_key_set = set(item_keys)
        relations = self.relation_source.load_relations()
        by_item_key: dict[str, list[ConnectedRelation]] = {
            item_key: [] for item_key in item_keys
        }

        for relation in relations:
            if relation.source_key in item_key_set:
                by_item_key[relation.source_key].append(
                    ConnectedRelation(
                        direction="outgoing",
                        source_key=relation.source_key,
                        relation_type=relation.relation_type,
                        target_key=relation.target_key,
                        source_table=relation.source_table,
                        rowid=relation.rowid,
                    )
                )

            if relation.target_key in item_key_set:
                by_item_key[relation.target_key].append(
                    ConnectedRelation(
                        direction="incoming",
                        source_key=relation.source_key,
                        relation_type=relation.relation_type,
                        target_key=relation.target_key,
                        source_table=relation.source_table,
                        rowid=relation.rowid,
                    )
                )

        return {
            item_key: tuple(relations_for_item)
            for item_key, relations_for_item in by_item_key.items()
        }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Lookup LanguageOS items from the SQLite index.",
    )
    parser.add_argument(
        "query",
        type=str,
        help="Search query. Can be a full item key or normalized text.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(r"D:\LanguageOS\Inbox\Indexes\languageos.db"),
        help="Path to languageos.db.",
    )
    parser.add_argument(
        "--type",
        dest="item_type",
        type=str,
        default=None,
        help="Optional item type filter, e.g. vocabulary, sentence, grammar.",
    )
    parser.add_argument(
        "--language",
        type=str,
        default=None,
        help="Optional language filter, e.g. english, german.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of matches.",
    )
    parser.add_argument(
        "--with-relations",
        action="store_true",
        help="Show incoming/outgoing relations for matched items.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional JSON output path.",
    )
    return parser


def print_report(report: LookupReport, *, with_relations: bool) -> None:
    print("LanguageOS Lookup v1")
    print("=" * 80)
    print(f"Query  : {report.query}")
    print(f"DB     : {report.db_path}")
    print(f"Matches: {len(report.matches)}")
    print("-" * 80)

    if not report.matches:
        print("No matching items found.")
        return

    for index, match in enumerate(report.matches, start=1):
        item = match.item

        print(f"[{index}] {item.item_key}")
        print(f"    type     : {item.item_type}")
        print(f"    language : {item.language}")
        print(f"    normalized: {item.normalized}")
        print(f"    match    : {match.match_kind.value} score={match.score}")
        print(f"    source   : {item.source_table} rowid={item.rowid}")

        if item.title:
            print(f"    title    : {item.title}")
        if item.file_path:
            print(f"    file     : {item.file_path}")
        if item.text_preview:
            print(f"    preview  : {item.text_preview}")

        if with_relations:
            relations = report.connected_relations.get(item.item_key, ())
            if relations:
                print("    relations:")
                for relation in relations:
                    if relation.direction == "outgoing":
                        print(
                            f"      --> {relation.relation_type} --> "
                            f"{relation.target_key}"
                        )
                    else:
                        print(
                            f"      <-- {relation.relation_type} -- "
                            f"{relation.source_key}"
                        )
            else:
                print("    relations: none")


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    parser = build_arg_parser()
    args = parser.parse_args(argv)

    service = LookupService(db_path=args.db)
    report = service.lookup(
        query=args.query,
        item_type=args.item_type,
        language=args.language,
        limit=args.limit,
        with_relations=args.with_relations,
    )

    print_report(report, with_relations=args.with_relations)

    if args.output_json is not None:
        report.write_json(args.output_json)
        print("-" * 80)
        print(f"JSON report written: {args.output_json}")

    return 0
