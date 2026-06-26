from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from languageos_tools.core.normalization import (
    ItemKey,
    ItemKeyExtractor,
    MarkdownFrontmatterReader,
)


logger = logging.getLogger(__name__)


class RelationIntegritySeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class RelationRecord:
    source_key: str
    relation_type: str
    target_key: str
    source_table: str
    rowid: int | None = None
    evidence: str | None = None


@dataclass(frozen=True)
class RelationIntegrityIssue:
    severity: RelationIntegritySeverity
    code: str
    message: str
    source_key: str | None = None
    relation_type: str | None = None
    target_key: str | None = None
    db_table: str | None = None
    db_rowid: int | None = None
    detail: str | None = None


@dataclass(frozen=True)
class RelationIntegritySummary:
    known_item_count: int
    relation_count: int
    valid_relation_count: int
    error_count: int
    warning_count: int
    info_count: int
    issues_by_code: Mapping[str, int]
    relation_count_by_type: Mapping[str, int]

    @property
    def has_errors(self) -> bool:
        return self.error_count > 0


@dataclass(frozen=True)
class RelationIntegrityReport:
    db_path: str
    vault_path: str | None
    relation_types_path: str | None
    summary: RelationIntegritySummary
    issues: tuple[RelationIntegrityIssue, ...]
    relations: tuple[RelationRecord, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "db_path": self.db_path,
            "vault_path": self.vault_path,
            "relation_types_path": self.relation_types_path,
            "summary": dataclasses.asdict(self.summary),
            "issues": [
                {
                    **dataclasses.asdict(issue),
                    "severity": issue.severity.value,
                }
                for issue in self.issues
            ],
            "relations": [dataclasses.asdict(record) for record in self.relations],
        }

    def write_json(self, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(self.to_json_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class RelationTypeRegistryReader:
    """
    Flexible reader for relation type registries.

    It supports common shapes:
    - {"relation_types": {"uses_grammar": {...}}}
    - {"types": {"uses_grammar": {...}}}
    - {"uses_grammar": {...}}
    - [{"relation_type": "uses_grammar"}, ...]
    """

    RELATION_TYPE_KEYS = ("relation_type", "type", "name", "id")

    def load_relation_types(self, path: Path) -> frozenset[str]:
        if not path.exists():
            raise FileNotFoundError(f"Relation types registry does not exist: {path}")

        data = json.loads(path.read_text(encoding="utf-8"))
        relation_types = self._extract_relation_types(data)

        cleaned = frozenset(
            value.strip().casefold()
            for value in relation_types
            if value.strip()
        )

        if not cleaned:
            raise ValueError(f"No relation types could be loaded from {path}")

        return cleaned

    def _extract_relation_types(self, data: Any) -> set[str]:
        result: set[str] = set()

        if isinstance(data, list):
            for item in data:
                result.update(self._extract_relation_types(item))
            return result

        if not isinstance(data, dict):
            return result

        for registry_key in ("relation_types", "types", "relations"):
            raw_section = data.get(registry_key)
            if isinstance(raw_section, dict):
                result.update(str(key) for key in raw_section.keys())
                for value in raw_section.values():
                    result.update(self._extract_relation_types(value))
            elif isinstance(raw_section, list):
                result.update(self._extract_relation_types(raw_section))

        for key in self.RELATION_TYPE_KEYS:
            value = data.get(key)
            if isinstance(value, str):
                result.add(value)

        # If this object itself looks like a direct relation-type mapping,
        # collect snake_case-ish keys. This is intentionally conservative.
        for key, value in data.items():
            if (
                isinstance(key, str)
                and "_" in key
                and isinstance(value, (dict, str, list))
                and key not in {"schema_version", "description"}
            ):
                result.add(key)

        return result


class VaultItemKeySource:
    def __init__(
        self,
        vault_path: Path,
        *,
        frontmatter_reader: MarkdownFrontmatterReader | None = None,
        item_key_extractor: ItemKeyExtractor | None = None,
    ) -> None:
        self.vault_path = vault_path
        self.frontmatter_reader = frontmatter_reader or MarkdownFrontmatterReader()
        self.item_key_extractor = item_key_extractor or ItemKeyExtractor()

    def load_item_keys(self) -> frozenset[str]:
        if not self.vault_path.exists():
            raise FileNotFoundError(f"Vault path does not exist: {self.vault_path}")

        keys: set[str] = set()

        for path in sorted(self.vault_path.rglob("*.md")):
            frontmatter = self.frontmatter_reader.read_frontmatter(path)
            item_key = self.item_key_extractor.extract(frontmatter)

            if item_key is not None:
                keys.add(item_key.render())

        return frozenset(keys)


class DatabaseItemKeySource:
    KEY_COLUMNS = ("item_key", "key", "id")
    TYPE_COLUMNS = ("type", "item_type", "note_type")
    LANGUAGE_COLUMNS = ("language", "lang")
    NORMALIZED_COLUMNS = ("normalized", "normalized_text", "canonical")

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def load_item_keys(self) -> frozenset[str]:
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database path does not exist: {self.db_path}")

        keys: set[str] = set()

        with sqlite3.connect(str(self.db_path)) as connection:
            connection.row_factory = sqlite3.Row

            for table_name in self._list_tables(connection):
                columns = self._table_columns(connection, table_name)

                explicit_key_col = self._first_existing(columns, self.KEY_COLUMNS)
                type_col = self._first_existing(columns, self.TYPE_COLUMNS)
                language_col = self._first_existing(columns, self.LANGUAGE_COLUMNS)
                normalized_col = self._first_existing(columns, self.NORMALIZED_COLUMNS)

                if explicit_key_col is not None:
                    keys.update(
                        self._load_explicit_keys(
                            connection=connection,
                            table_name=table_name,
                            key_col=explicit_key_col,
                        )
                    )
                    continue

                if type_col and language_col and normalized_col:
                    keys.update(
                        self._load_composed_keys(
                            connection=connection,
                            table_name=table_name,
                            type_col=type_col,
                            language_col=language_col,
                            normalized_col=normalized_col,
                        )
                    )

        return frozenset(keys)

    def _list_tables(self, connection: sqlite3.Connection) -> tuple[str, ...]:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            ORDER BY name
            """
        ).fetchall()

        return tuple(
            str(row["name"])
            for row in rows
            if not str(row["name"]).startswith("sqlite_")
        )

    def _table_columns(
        self,
        connection: sqlite3.Connection,
        table_name: str,
    ) -> set[str]:
        rows = connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        return {str(row["name"]) for row in rows}

    def _first_existing(
        self,
        columns: set[str],
        candidates: Sequence[str],
    ) -> str | None:
        for candidate in candidates:
            if candidate in columns:
                return candidate
        return None

    def _load_explicit_keys(
        self,
        *,
        connection: sqlite3.Connection,
        table_name: str,
        key_col: str,
    ) -> set[str]:
        result: set[str] = set()

        query = f'''
            SELECT "{key_col}" AS item_key
            FROM "{table_name}"
            WHERE "{key_col}" IS NOT NULL
        '''

        for row in connection.execute(query):
            value = str(row["item_key"]).strip()
            if not value:
                continue

            try:
                result.add(ItemKey.parse(value).render())
            except ValueError:
                continue

        return result

    def _load_composed_keys(
        self,
        *,
        connection: sqlite3.Connection,
        table_name: str,
        type_col: str,
        language_col: str,
        normalized_col: str,
    ) -> set[str]:
        result: set[str] = set()

        query = f'''
            SELECT
                "{type_col}" AS item_type,
                "{language_col}" AS language,
                "{normalized_col}" AS normalized
            FROM "{table_name}"
            WHERE "{type_col}" IS NOT NULL
              AND "{language_col}" IS NOT NULL
              AND "{normalized_col}" IS NOT NULL
        '''

        for row in connection.execute(query):
            item_type = str(row["item_type"]).strip()
            language = str(row["language"]).strip()
            normalized = str(row["normalized"]).strip()

            if item_type and language and normalized:
                result.add(
                    ItemKey(
                        item_type=item_type,
                        language=language,
                        normalized=normalized,
                    ).render()
                )

        return result


class DatabaseRelationSource:
    SOURCE_COLUMNS = ("source_key", "source", "from_key", "from_item_key")
    TARGET_COLUMNS = ("target_key", "target", "to_key", "to_item_key")
    TYPE_COLUMNS = ("relation_type", "type", "edge_type")
    EVIDENCE_COLUMNS = ("evidence", "section", "source_file", "note_path")

    PREFERRED_TABLE_NAMES = (
        "relations",
        "relation_index",
        "item_relations",
        "language_relations",
    )

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def load_relations(self) -> tuple[RelationRecord, ...]:
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database path does not exist: {self.db_path}")

        records: list[RelationRecord] = []

        with sqlite3.connect(str(self.db_path)) as connection:
            connection.row_factory = sqlite3.Row

            for table_name in self._relation_tables(connection):
                records.extend(self._load_table_relations(connection, table_name))

        return tuple(records)

    def _relation_tables(self, connection: sqlite3.Connection) -> tuple[str, ...]:
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

        relation_like = [
            table_name
            for table_name in table_names
            if "relation" in table_name.casefold()
        ]

        preferred = [
            table_name
            for table_name in self.PREFERRED_TABLE_NAMES
            if table_name in table_names
        ]

        ordered: list[str] = []
        for table_name in preferred + relation_like:
            if table_name not in ordered:
                ordered.append(table_name)

        return tuple(ordered)

    def _load_table_relations(
        self,
        connection: sqlite3.Connection,
        table_name: str,
    ) -> list[RelationRecord]:
        columns = self._table_columns(connection, table_name)

        source_col = self._first_existing(columns, self.SOURCE_COLUMNS)
        target_col = self._first_existing(columns, self.TARGET_COLUMNS)
        type_col = self._first_existing(columns, self.TYPE_COLUMNS)
        evidence_col = self._first_existing(columns, self.EVIDENCE_COLUMNS)

        if not source_col or not target_col or not type_col:
            logger.debug(
                "Skipping relation-like table %s because required columns were not found.",
                table_name,
            )
            return []

        select_parts = [
            "rowid AS __rowid__",
            f'"{source_col}" AS source_key',
            f'"{type_col}" AS relation_type',
            f'"{target_col}" AS target_key',
        ]

        if evidence_col is not None:
            select_parts.append(f'"{evidence_col}" AS evidence')
        else:
            select_parts.append("NULL AS evidence")

        query = f'''
            SELECT {", ".join(select_parts)}
            FROM "{table_name}"
            WHERE "{source_col}" IS NOT NULL
              AND "{type_col}" IS NOT NULL
              AND "{target_col}" IS NOT NULL
        '''

        records: list[RelationRecord] = []
        for row in connection.execute(query):
            source_key = str(row["source_key"]).strip()
            relation_type = str(row["relation_type"]).strip().casefold()
            target_key = str(row["target_key"]).strip()

            if not source_key or not relation_type or not target_key:
                continue

            records.append(
                RelationRecord(
                    source_key=source_key,
                    relation_type=relation_type,
                    target_key=target_key,
                    source_table=table_name,
                    rowid=int(row["__rowid__"]),
                    evidence=(
                        str(row["evidence"]).strip()
                        if row["evidence"] is not None
                        else None
                    ),
                )
            )

        return records

    def _table_columns(
        self,
        connection: sqlite3.Connection,
        table_name: str,
    ) -> set[str]:
        rows = connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        return {str(row["name"]) for row in rows}

    def _first_existing(
        self,
        columns: set[str],
        candidates: Sequence[str],
    ) -> str | None:
        for candidate in candidates:
            if candidate in columns:
                return candidate
        return None


class RelationIntegrityAuditService:
    def __init__(
        self,
        *,
        db_path: Path,
        vault_path: Path | None = None,
        relation_types_path: Path | None = None,
    ) -> None:
        self.db_path = db_path
        self.vault_path = vault_path
        self.relation_types_path = relation_types_path

    def audit(self) -> RelationIntegrityReport:
        known_item_keys = self._load_known_item_keys()
        relation_types = self._load_relation_types()
        relations = DatabaseRelationSource(self.db_path).load_relations()

        issues = self._audit_relations(
            relations=relations,
            known_item_keys=known_item_keys,
            relation_types=relation_types,
        )

        if not relations:
            issues.append(
                RelationIntegrityIssue(
                    severity=RelationIntegritySeverity.ERROR,
                    code="no_relations_found",
                    message=(
                        "No relations were found in the database. "
                        "Run rebuild_relation_index.py or check relation table schema."
                    ),
                    detail=str(self.db_path),
                )
            )

        return RelationIntegrityReport(
            db_path=str(self.db_path),
            vault_path=str(self.vault_path) if self.vault_path is not None else None,
            relation_types_path=(
                str(self.relation_types_path)
                if self.relation_types_path is not None
                else None
            ),
            summary=self._summarize(
                known_item_keys=known_item_keys,
                relations=relations,
                issues=issues,
            ),
            issues=tuple(issues),
            relations=relations,
        )

    def _load_known_item_keys(self) -> frozenset[str]:
        keys: set[str] = set()

        keys.update(DatabaseItemKeySource(self.db_path).load_item_keys())

        if self.vault_path is not None:
            keys.update(VaultItemKeySource(self.vault_path).load_item_keys())

        return frozenset(keys)

    def _load_relation_types(self) -> frozenset[str]:
        if self.relation_types_path is None:
            return frozenset()

        return RelationTypeRegistryReader().load_relation_types(self.relation_types_path)

    def _audit_relations(
        self,
        *,
        relations: Sequence[RelationRecord],
        known_item_keys: frozenset[str],
        relation_types: frozenset[str],
    ) -> list[RelationIntegrityIssue]:
        issues: list[RelationIntegrityIssue] = []

        duplicate_map: dict[tuple[str, str, str], list[RelationRecord]] = defaultdict(list)
        for relation in relations:
            duplicate_map[
                (
                    relation.source_key,
                    relation.relation_type,
                    relation.target_key,
                )
            ].append(relation)

        for relation in relations:
            if relation_types and relation.relation_type not in relation_types:
                issues.append(
                    self._issue(
                        relation=relation,
                        severity=RelationIntegritySeverity.ERROR,
                        code="unknown_relation_type",
                        message=(
                            f"Unknown relation type: {relation.relation_type!r}."
                        ),
                    )
                )

            if known_item_keys and relation.source_key not in known_item_keys:
                issues.append(
                    self._issue(
                        relation=relation,
                        severity=RelationIntegritySeverity.ERROR,
                        code="dangling_source",
                        message="Relation source key does not exist in known items.",
                    )
                )

            if known_item_keys and relation.target_key not in known_item_keys:
                issues.append(
                    self._issue(
                        relation=relation,
                        severity=RelationIntegritySeverity.ERROR,
                        code="dangling_target",
                        message="Relation target key does not exist in known items.",
                    )
                )

        for duplicate_key, duplicate_records in duplicate_map.items():
            if len(duplicate_records) <= 1:
                continue

            first = duplicate_records[0]
            issues.append(
                self._issue(
                    relation=first,
                    severity=RelationIntegritySeverity.WARNING,
                    code="duplicate_relation",
                    message=(
                        "Duplicate relation detected for "
                        f"{duplicate_key[0]} --{duplicate_key[1]}--> {duplicate_key[2]}"
                    ),
                    detail=(
                        "rows="
                        + ", ".join(
                            str(record.rowid)
                            for record in duplicate_records
                            if record.rowid is not None
                        )
                    ),
                )
            )

        return issues

    def _issue(
        self,
        *,
        relation: RelationRecord,
        severity: RelationIntegritySeverity,
        code: str,
        message: str,
        detail: str | None = None,
    ) -> RelationIntegrityIssue:
        return RelationIntegrityIssue(
            severity=severity,
            code=code,
            message=message,
            source_key=relation.source_key,
            relation_type=relation.relation_type,
            target_key=relation.target_key,
            db_table=relation.source_table,
            db_rowid=relation.rowid,
            detail=detail,
        )

    def _summarize(
        self,
        *,
        known_item_keys: frozenset[str],
        relations: Sequence[RelationRecord],
        issues: Sequence[RelationIntegrityIssue],
    ) -> RelationIntegritySummary:
        severity_counter = Counter(issue.severity for issue in issues)
        issue_code_counter = Counter(issue.code for issue in issues)
        relation_type_counter = Counter(relation.relation_type for relation in relations)

        invalid_relation_rowids = {
            issue.db_rowid
            for issue in issues
            if issue.severity == RelationIntegritySeverity.ERROR
            and issue.db_rowid is not None
        }

        valid_relation_count = sum(
            1
            for relation in relations
            if relation.rowid not in invalid_relation_rowids
        )

        return RelationIntegritySummary(
            known_item_count=len(known_item_keys),
            relation_count=len(relations),
            valid_relation_count=valid_relation_count,
            error_count=severity_counter[RelationIntegritySeverity.ERROR],
            warning_count=severity_counter[RelationIntegritySeverity.WARNING],
            info_count=severity_counter[RelationIntegritySeverity.INFO],
            issues_by_code=dict(issue_code_counter),
            relation_count_by_type=dict(relation_type_counter),
        )


def build_arg_parser() -> argparse.ArgumentParser:
    project_root = Path(__file__).resolve().parents[3]

    parser = argparse.ArgumentParser(
        description="Audit LanguageOS relation index integrity.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        required=True,
        help="Path to languageos.db.",
    )
    parser.add_argument(
        "--vault",
        type=Path,
        default=None,
        help="Optional Obsidian vault path for extra known item keys.",
    )
    parser.add_argument(
        "--relation-types",
        type=Path,
        default=project_root
        / "src"
        / "languageos_tools"
        / "relations"
        / "relation_types.json",
        help="Path to relation type registry JSON.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional JSON report path.",
    )
    parser.add_argument(
        "--no-fail-on-error",
        action="store_true",
        help="Return exit code 0 even when integrity errors are found.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of issues to print.",
    )
    return parser


def print_report(report: RelationIntegrityReport, *, limit: int) -> None:
    print("LanguageOS Relation Integrity Audit v1")
    print("=" * 80)
    print(f"Known items     : {report.summary.known_item_count}")
    print(f"Relations       : {report.summary.relation_count}")
    print(f"Valid relations : {report.summary.valid_relation_count}")
    print(f"Errors          : {report.summary.error_count}")
    print(f"Warnings        : {report.summary.warning_count}")
    print(f"Info            : {report.summary.info_count}")

    if report.summary.relation_count_by_type:
        print(f"Relations by type: {dict(report.summary.relation_count_by_type)}")
    if report.summary.issues_by_code:
        print(f"Issues by code  : {dict(report.summary.issues_by_code)}")

    print("-" * 80)

    if not report.issues:
        print("No relation integrity issues found.")
        return

    for index, issue in enumerate(report.issues[:limit], start=1):
        print(f"[{index}] {issue.severity.value.upper()} {issue.code}")
        print(f"    message : {issue.message}")

        if issue.db_table is not None:
            print(f"    table   : {issue.db_table}")
        if issue.db_rowid is not None:
            print(f"    rowid   : {issue.db_rowid}")
        if issue.source_key is not None:
            print(f"    source  : {issue.source_key}")
        if issue.relation_type is not None:
            print(f"    type    : {issue.relation_type}")
        if issue.target_key is not None:
            print(f"    target  : {issue.target_key}")
        if issue.detail is not None:
            print(f"    detail  : {issue.detail}")

    if len(report.issues) > limit:
        print(f"... truncated {len(report.issues) - limit} issues. Use --limit to show more.")


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    parser = build_arg_parser()
    args = parser.parse_args(argv)

    service = RelationIntegrityAuditService(
        db_path=args.db,
        vault_path=args.vault,
        relation_types_path=args.relation_types,
    )
    report = service.audit()

    print_report(report, limit=args.limit)

    if args.output_json is not None:
        report.write_json(args.output_json)
        print("-" * 80)
        print(f"JSON report written: {args.output_json}")

    if report.summary.has_errors and not args.no_fail_on_error:
        return 1

    return 0