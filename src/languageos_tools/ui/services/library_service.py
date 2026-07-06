from __future__ import annotations

import dataclasses
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LibraryFilter:
    query: str = ""
    language: str = "all"
    item_type: str = "all"
    status: str = "all"
    anki_status: str = "all"
    level: str = "all"
    source_type: str = "all"
    review_status: str = "all"
    review_priority: str = "all"
    topic: str = "all"
    skill: str = "all"
    limit: int = 100


@dataclass(frozen=True)
class LibraryItemView:
    item_id: int
    item_key: str
    item_type: str
    language: str
    text: str
    normalized: str
    status: str
    anki_status: str
    level: str
    source_type: str
    review_status: str
    review_priority: str
    obsidian_path: str
    topics: tuple[str, ...]
    skills: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        result = dataclasses.asdict(self)
        result["topics"] = list(self.topics)
        result["skills"] = list(self.skills)
        return result


@dataclass(frozen=True)
class LibraryFacetOptions:
    languages: tuple[str, ...]
    item_types: tuple[str, ...]
    statuses: tuple[str, ...]
    anki_statuses: tuple[str, ...]
    levels: tuple[str, ...]
    source_types: tuple[str, ...]
    review_statuses: tuple[str, ...]
    review_priorities: tuple[str, ...]
    topics: tuple[str, ...]
    skills: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class LibraryLookupView:
    db_path: str
    db_exists: bool
    filters: LibraryFilter
    items: tuple[LibraryItemView, ...]
    facets: LibraryFacetOptions

    @property
    def has_items(self) -> bool:
        return bool(self.items)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "db_path": self.db_path,
            "db_exists": self.db_exists,
            "filters": dataclasses.asdict(self.filters),
            "items": [item.to_json_dict() for item in self.items],
            "facets": self.facets.to_json_dict(),
        }


class LibraryService:
    """
    Metadata-aware library service for the learner UI.

    This service reads the SQLite index/cache only. It does not mutate the
    database and does not modify Obsidian notes. Obsidian remains the source of
    truth; this service only provides learner-friendly browsing/filtering.
    """

    DEFAULT_LIMIT = 100
    MAX_LIMIT = 500

    def __init__(self, *, db_path: Path) -> None:
        self.db_path = db_path

    def lookup(self, filters: LibraryFilter | None = None) -> LibraryLookupView:
        active_filters = filters or LibraryFilter()
        normalized_filters = self._normalize_filters(active_filters)

        if not self.db_path.exists():
            return LibraryLookupView(
                db_path=str(self.db_path),
                db_exists=False,
                filters=normalized_filters,
                items=(),
                facets=self._empty_facets(),
            )

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            tables = self._list_tables(conn)

            if "items" not in tables:
                return LibraryLookupView(
                    db_path=str(self.db_path),
                    db_exists=True,
                    filters=normalized_filters,
                    items=(),
                    facets=self._empty_facets(),
                )

            items = self._query_items(conn, normalized_filters)
            facets = self._load_facets(conn, tables)

        return LibraryLookupView(
            db_path=str(self.db_path),
            db_exists=True,
            filters=normalized_filters,
            items=items,
            facets=facets,
        )

    def _query_items(
        self,
        conn: sqlite3.Connection,
        filters: LibraryFilter,
    ) -> tuple[LibraryItemView, ...]:
        where_clauses: list[str] = []
        params: list[object] = []

        self._add_exact_filter(where_clauses, params, "i.language", filters.language)
        self._add_exact_filter(where_clauses, params, "i.type", filters.item_type)
        self._add_exact_filter(where_clauses, params, "i.status", filters.status)
        self._add_exact_filter(
            where_clauses,
            params,
            "i.anki_status",
            filters.anki_status,
        )
        self._add_exact_filter(where_clauses, params, "i.level", filters.level)
        self._add_exact_filter(
            where_clauses,
            params,
            "i.source_type",
            filters.source_type,
        )
        self._add_exact_filter(
            where_clauses,
            params,
            "a.review_status",
            filters.review_status,
        )
        self._add_exact_filter(
            where_clauses,
            params,
            "a.review_priority",
            filters.review_priority,
        )

        clean_query = filters.query.strip().casefold()
        if clean_query:
            like_query = f"%{clean_query}%"
            where_clauses.append(
                """
                (
                    lower(coalesce(i.text, '')) LIKE ?
                    OR lower(coalesce(i.normalized, '')) LIKE ?
                    OR lower(coalesce(i.obsidian_path, '')) LIKE ?
                    OR lower(coalesce(i.source, '')) LIKE ?
                )
                """
            )
            params.extend([like_query, like_query, like_query, like_query])

        if self._is_active_filter(filters.topic):
            where_clauses.append(
                """
                EXISTS (
                    SELECT 1
                    FROM item_topics it
                    JOIN topics t ON t.id = it.topic_id
                    WHERE it.item_id = i.id
                      AND lower(t.name) = ?
                )
                """
            )
            params.append(filters.topic.casefold())

        if self._is_active_filter(filters.skill):
            where_clauses.append(
                """
                EXISTS (
                    SELECT 1
                    FROM item_skills isk
                    JOIN skills s ON s.id = isk.skill_id
                    WHERE isk.item_id = i.id
                      AND lower(s.name) = ?
                )
                """
            )
            params.append(filters.skill.casefold())

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        sql = f"""
            SELECT
                i.id AS item_id,
                i.type AS item_type,
                i.language AS language,
                i.text AS text,
                i.normalized AS normalized,
                i.status AS status,
                i.anki_status AS anki_status,
                i.level AS level,
                i.source_type AS source_type,
                i.obsidian_path AS obsidian_path,
                a.review_status AS review_status,
                a.review_priority AS review_priority
            FROM items i
            LEFT JOIN item_activity a
              ON a.item_key = (
                  coalesce(i.type, '')
                  || '|'
                  || coalesce(i.language, '')
                  || '|'
                  || coalesce(i.normalized, '')
              )
            {where_sql}
            ORDER BY
                lower(coalesce(i.language, '')),
                lower(coalesce(i.type, '')),
                lower(coalesce(i.normalized, ''))
            LIMIT ?
        """

        params.append(filters.limit)
        rows = conn.execute(sql, params).fetchall()

        return tuple(self._row_to_item_view(conn, row) for row in rows)

    def _row_to_item_view(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> LibraryItemView:
        item_type = self._clean_value(row["item_type"])
        language = self._clean_value(row["language"])
        normalized = self._clean_value(row["normalized"])
        item_key = self._build_item_key(
            item_type=item_type,
            language=language,
            normalized=normalized,
        )

        item_id = int(row["item_id"])

        return LibraryItemView(
            item_id=item_id,
            item_key=item_key,
            item_type=item_type,
            language=language,
            text=self._clean_value(row["text"]),
            normalized=normalized,
            status=self._clean_value(row["status"]),
            anki_status=self._clean_value(row["anki_status"]),
            level=self._clean_value(row["level"]),
            source_type=self._clean_value(row["source_type"]),
            review_status=self._clean_value(row["review_status"]),
            review_priority=self._clean_value(row["review_priority"]),
            obsidian_path=self._clean_value(row["obsidian_path"]),
            topics=self._load_item_labels(
                conn=conn,
                item_id=item_id,
                bridge_table="item_topics",
                label_table="topics",
                bridge_id_column="topic_id",
            ),
            skills=self._load_item_labels(
                conn=conn,
                item_id=item_id,
                bridge_table="item_skills",
                label_table="skills",
                bridge_id_column="skill_id",
            ),
        )

    def _load_item_labels(
        self,
        *,
        conn: sqlite3.Connection,
        item_id: int,
        bridge_table: str,
        label_table: str,
        bridge_id_column: str,
    ) -> tuple[str, ...]:
        sql = f"""
            SELECT label.name
            FROM {bridge_table} bridge
            JOIN {label_table} label
              ON label.id = bridge.{bridge_id_column}
            WHERE bridge.item_id = ?
            ORDER BY lower(label.name)
        """
        rows = conn.execute(sql, (item_id,)).fetchall()
        return tuple(str(row[0]) for row in rows if str(row[0]).strip())

    def _load_facets(
        self,
        conn: sqlite3.Connection,
        tables: set[str],
    ) -> LibraryFacetOptions:
        return LibraryFacetOptions(
            languages=self._load_distinct_values(conn, "items", "language"),
            item_types=self._load_distinct_values(conn, "items", "type"),
            statuses=self._load_distinct_values(conn, "items", "status"),
            anki_statuses=self._load_distinct_values(conn, "items", "anki_status"),
            levels=self._load_distinct_values(conn, "items", "level"),
            source_types=self._load_distinct_values(conn, "items", "source_type"),
            review_statuses=(
                self._load_distinct_values(
                    conn,
                    "item_activity",
                    "review_status",
                )
                if "item_activity" in tables
                else ()
            ),
            review_priorities=(
                self._load_distinct_values(
                    conn,
                    "item_activity",
                    "review_priority",
                )
                if "item_activity" in tables
                else ()
            ),
            topics=(
                self._load_distinct_values(conn, "topics", "name")
                if "topics" in tables
                else ()
            ),
            skills=(
                self._load_distinct_values(conn, "skills", "name")
                if "skills" in tables
                else ()
            ),
        )

    def _load_distinct_values(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        column_name: str,
    ) -> tuple[str, ...]:
        safe_table = table_name.replace('"', '""')
        safe_column = column_name.replace('"', '""')

        rows = conn.execute(
            f"""
            SELECT DISTINCT "{safe_column}"
            FROM "{safe_table}"
            WHERE "{safe_column}" IS NOT NULL
              AND trim("{safe_column}") != ''
            ORDER BY lower("{safe_column}")
            """
        ).fetchall()

        return tuple(str(row[0]) for row in rows)

    def _normalize_filters(self, filters: LibraryFilter) -> LibraryFilter:
        limit = max(1, min(filters.limit, self.MAX_LIMIT))

        return LibraryFilter(
            query=filters.query.strip(),
            language=self._normalize_filter_value(filters.language),
            item_type=self._normalize_filter_value(filters.item_type),
            status=self._normalize_filter_value(filters.status),
            anki_status=self._normalize_filter_value(filters.anki_status),
            level=self._normalize_filter_value(filters.level),
            source_type=self._normalize_filter_value(filters.source_type),
            review_status=self._normalize_filter_value(filters.review_status),
            review_priority=self._normalize_filter_value(filters.review_priority),
            topic=self._normalize_filter_value(filters.topic),
            skill=self._normalize_filter_value(filters.skill),
            limit=limit,
        )

    def _normalize_filter_value(self, value: str) -> str:
        clean_value = value.strip().casefold()
        return clean_value or "all"

    def _add_exact_filter(
        self,
        where_clauses: list[str],
        params: list[object],
        column_sql: str,
        value: str,
    ) -> None:
        if not self._is_active_filter(value):
            return

        where_clauses.append(f"lower(coalesce({column_sql}, '')) = ?")
        params.append(value.casefold())

    def _is_active_filter(self, value: str) -> bool:
        return bool(value.strip()) and value.strip().casefold() != "all"

    def _list_tables(self, conn: sqlite3.Connection) -> set[str]:
        rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            """
        ).fetchall()
        return {str(row[0]) for row in rows}

    def _empty_facets(self) -> LibraryFacetOptions:
        return LibraryFacetOptions(
            languages=(),
            item_types=(),
            statuses=(),
            anki_statuses=(),
            levels=(),
            source_types=(),
            review_statuses=(),
            review_priorities=(),
            topics=(),
            skills=(),
        )

    def _build_item_key(
        self,
        *,
        item_type: str,
        language: str,
        normalized: str,
    ) -> str:
        return f"{item_type}|{language}|{normalized}"

    def _clean_value(self, value: object | None) -> str:
        if value is None:
            return ""

        return str(value).strip()