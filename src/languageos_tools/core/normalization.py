from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import re
import sqlite3
import unicodedata
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


logger = logging.getLogger(__name__)


class NormalizationProfile(str, Enum):
    """
    Named normalization profiles.

    Profiles are intentionally versioned so future changes can be audited,
    migrated, and backfilled without silently changing existing keys.
    """

    LEGACY_V1 = "legacy_v1"
    KEY_V1 = "key_v1"


@dataclass(frozen=True)
class NormalizationConfig:
    """
    Configuration for item key normalization.

    Notes
    -----
    - `strip_terminal_punctuation_item_types` is deliberately item-type aware.
      This avoids accidentally changing vocabulary/grammar notes where terminal
      punctuation can be meaningful, e.g. abbreviations.
    - This class is immutable so audits are reproducible.
    """

    profile: NormalizationProfile = NormalizationProfile.KEY_V1
    lowercase: bool = True
    unicode_form: str = "NFKC"
    collapse_whitespace: bool = True
    trim: bool = True
    strip_terminal_punctuation_item_types: frozenset[str] = frozenset({"sentence"})
    terminal_punctuation_pattern: str = r"[.!?。！？]+$"


@dataclass(frozen=True)
class NormalizationResult:
    original: str
    normalized: str
    profile: NormalizationProfile
    changed: bool
    operations: tuple[str, ...]


@dataclass(frozen=True)
class ItemKey:
    """
    Canonical LanguageOS item key representation.

    Format:
        item_type|language|normalized
    """

    item_type: str
    language: str
    normalized: str

    @classmethod
    def parse(cls, value: str) -> "ItemKey":
        parts = value.split("|", maxsplit=2)
        if len(parts) != 3:
            raise ValueError(
                f"Invalid item key format: {value!r}. "
                "Expected: item_type|language|normalized"
            )

        item_type, language, normalized = parts
        return cls(
            item_type=item_type.strip(),
            language=language.strip(),
            normalized=normalized.strip(),
        )

    def render(self) -> str:
        return f"{self.item_type}|{self.language}|{self.normalized}"


@dataclass(frozen=True)
class KeyAuditRecord:
    source: str
    item_key: str
    proposed_key: str
    item_type: str
    language: str
    current_normalized: str
    proposed_normalized: str
    changed: bool
    operations: tuple[str, ...]
    file_path: str | None = None
    db_rowid: int | None = None
    note_title: str | None = None


@dataclass(frozen=True)
class KeyAuditSummary:
    total_records: int
    changed_records: int
    unchanged_records: int
    changed_by_item_type: Mapping[str, int]
    changed_by_language: Mapping[str, int]

    @property
    def has_changes(self) -> bool:
        return self.changed_records > 0


@dataclass(frozen=True)
class KeyAuditReport:
    config: NormalizationConfig
    records: tuple[KeyAuditRecord, ...]
    summary: KeyAuditSummary

    def changed_records(self) -> tuple[KeyAuditRecord, ...]:
        return tuple(record for record in self.records if record.changed)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "profile": self.config.profile.value,
            "summary": dataclasses.asdict(self.summary),
            "records": [
                {
                    "source": record.source,
                    "item_key": record.item_key,
                    "proposed_key": record.proposed_key,
                    "item_type": record.item_type,
                    "language": record.language,
                    "current_normalized": record.current_normalized,
                    "proposed_normalized": record.proposed_normalized,
                    "changed": record.changed,
                    "operations": list(record.operations),
                    "file_path": record.file_path,
                    "db_rowid": record.db_rowid,
                    "note_title": record.note_title,
                }
                for record in self.records
            ],
        }

    def write_json(self, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(self.to_json_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class ItemKeyNormalizer:
    """
    Versioned normalizer for LanguageOS item keys.

    This class only computes proposed values. It does not mutate notes or the DB.
    """

    def __init__(self, config: NormalizationConfig | None = None) -> None:
        self.config = config or NormalizationConfig()
        self._terminal_punctuation_re = re.compile(
            self.config.terminal_punctuation_pattern
        )

    def normalize_text(self, text: str, *, item_type: str | None = None) -> NormalizationResult:
        operations: list[str] = []
        value = text

        unicode_value = unicodedata.normalize(self.config.unicode_form, value)
        if unicode_value != value:
            operations.append(f"unicode:{self.config.unicode_form}")
            value = unicode_value

        if self.config.trim:
            trimmed = value.strip()
            if trimmed != value:
                operations.append("trim")
                value = trimmed

        if self.config.collapse_whitespace:
            collapsed = re.sub(r"\s+", " ", value)
            if collapsed != value:
                operations.append("collapse_whitespace")
                value = collapsed

        if self.config.lowercase:
            lowered = value.casefold()
            if lowered != value:
                operations.append("casefold")
                value = lowered

        normalized_item_type = (item_type or "").strip().casefold()
        if normalized_item_type in self.config.strip_terminal_punctuation_item_types:
            stripped = self._terminal_punctuation_re.sub("", value).strip()
            if stripped != value:
                operations.append("strip_terminal_punctuation")
                value = stripped

        return NormalizationResult(
            original=text,
            normalized=value,
            profile=self.config.profile,
            changed=value != text,
            operations=tuple(operations),
        )

    def normalize_item_key(self, item_key: ItemKey) -> tuple[ItemKey, NormalizationResult]:
        result = self.normalize_text(
            item_key.normalized,
            item_type=item_key.item_type,
        )
        proposed = ItemKey(
            item_type=item_key.item_type.strip().casefold(),
            language=item_key.language.strip().casefold(),
            normalized=result.normalized,
        )
        return proposed, result


class MarkdownFrontmatterReader:
    """
    Lightweight YAML-frontmatter reader for audit purposes.

    It intentionally supports the subset normally used by LanguageOS notes:
    simple `key: value` pairs. If your existing `core.frontmatter` has richer
    parsing, this reader can later be replaced behind the same audit interface.
    """

    FRONTMATTER_BOUNDARY = "---"

    def read_frontmatter(self, path: Path) -> dict[str, Any]:
        text = path.read_text(encoding="utf-8")

        if not text.startswith(self.FRONTMATTER_BOUNDARY):
            return {}

        lines = text.splitlines()
        if not lines or lines[0].strip() != self.FRONTMATTER_BOUNDARY:
            return {}

        end_index = None
        for index in range(1, len(lines)):
            if lines[index].strip() == self.FRONTMATTER_BOUNDARY:
                end_index = index
                break

        if end_index is None:
            return {}

        frontmatter_lines = lines[1:end_index]
        return self._parse_simple_yaml(frontmatter_lines)

    def _parse_simple_yaml(self, lines: Sequence[str]) -> dict[str, Any]:
        data: dict[str, Any] = {}

        for raw_line in lines:
            line = raw_line.strip()

            if not line or line.startswith("#"):
                continue

            if ":" not in line:
                continue

            key, raw_value = line.split(":", maxsplit=1)
            key = key.strip()
            value = raw_value.strip()

            if not key:
                continue

            data[key] = self._parse_scalar(value)

        return data

    def _parse_scalar(self, value: str) -> Any:
        if value in {"", "null", "Null", "NULL", "~"}:
            return None

        if value in {"true", "True", "TRUE"}:
            return True

        if value in {"false", "False", "FALSE"}:
            return False

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {'"', "'"}
        ):
            return value[1:-1]

        return value


class ItemKeyExtractor:
    """
    Extracts item key components from note frontmatter.

    Supports both:
    - explicit item_key field
    - composed fields: type/language/normalized
    """

    ITEM_KEY_FIELDS = ("item_key", "key", "id")
    TYPE_FIELDS = ("type", "item_type", "note_type")
    LANGUAGE_FIELDS = ("language", "lang")
    NORMALIZED_FIELDS = ("normalized", "normalized_text", "canonical")

    def extract(self, frontmatter: Mapping[str, Any]) -> ItemKey | None:
        explicit_key = self._first_str(frontmatter, self.ITEM_KEY_FIELDS)
        if explicit_key:
            try:
                return ItemKey.parse(explicit_key)
            except ValueError:
                logger.debug("Invalid explicit item key in frontmatter: %r", explicit_key)

        item_type = self._first_str(frontmatter, self.TYPE_FIELDS)
        language = self._first_str(frontmatter, self.LANGUAGE_FIELDS)
        normalized = self._first_str(frontmatter, self.NORMALIZED_FIELDS)

        if item_type and language and normalized:
            return ItemKey(
                item_type=item_type,
                language=language,
                normalized=normalized,
            )

        return None

    def _first_str(
        self,
        frontmatter: Mapping[str, Any],
        fields: Iterable[str],
    ) -> str | None:
        for field in fields:
            value = frontmatter.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None


class VaultKeyAuditSource:
    """
    Reads item keys from Markdown notes in an Obsidian vault.
    """

    def __init__(
        self,
        vault_path: Path,
        frontmatter_reader: MarkdownFrontmatterReader | None = None,
        key_extractor: ItemKeyExtractor | None = None,
    ) -> None:
        self.vault_path = vault_path
        self.frontmatter_reader = frontmatter_reader or MarkdownFrontmatterReader()
        self.key_extractor = key_extractor or ItemKeyExtractor()

    def iter_items(self) -> Iterable[tuple[ItemKey, dict[str, Any]]]:
        if not self.vault_path.exists():
            raise FileNotFoundError(f"Vault path does not exist: {self.vault_path}")

        for path in sorted(self.vault_path.rglob("*.md")):
            try:
                frontmatter = self.frontmatter_reader.read_frontmatter(path)
            except UnicodeDecodeError as exc:
                logger.warning("Skipping non-UTF8 markdown file %s: %s", path, exc)
                continue

            item_key = self.key_extractor.extract(frontmatter)
            if item_key is None:
                continue

            yield item_key, {
                "source": "vault",
                "file_path": str(path),
                "note_title": path.stem,
            }


class DatabaseKeyAuditSource:
    """
    Reads item keys from the SQLite LanguageOS index.

    The repository layer can later replace this source, but direct SQLite is
    useful for audit because table schemas may evolve. This class discovers a
    compatible table shape conservatively and only reads data.
    """

    CANDIDATE_TABLES = (
        "items",
        "language_items",
        "notes",
        "documents",
        "fts_documents",
    )

    TYPE_COLUMNS = ("type", "item_type", "note_type")
    LANGUAGE_COLUMNS = ("language", "lang")
    NORMALIZED_COLUMNS = ("normalized", "normalized_text", "canonical")
    KEY_COLUMNS = ("item_key", "key", "id")

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def iter_items(self) -> Iterable[tuple[ItemKey, dict[str, Any]]]:
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database path does not exist: {self.db_path}")

        with sqlite3.connect(str(self.db_path)) as connection:
            connection.row_factory = sqlite3.Row

            for table_name in self._list_tables(connection):
                table_info = self._table_info(connection, table_name)
                columns = {column["name"] for column in table_info}

                explicit_key_col = self._first_existing(columns, self.KEY_COLUMNS)
                type_col = self._first_existing(columns, self.TYPE_COLUMNS)
                language_col = self._first_existing(columns, self.LANGUAGE_COLUMNS)
                normalized_col = self._first_existing(columns, self.NORMALIZED_COLUMNS)

                if explicit_key_col:
                    yield from self._iter_explicit_key_rows(
                        connection,
                        table_name,
                        explicit_key_col,
                    )
                    continue

                if type_col and language_col and normalized_col:
                    yield from self._iter_composed_key_rows(
                        connection,
                        table_name,
                        type_col,
                        language_col,
                        normalized_col,
                    )

    def _list_tables(self, connection: sqlite3.Connection) -> tuple[str, ...]:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            ORDER BY name
            """
        ).fetchall()

        table_names = tuple(str(row["name"]) for row in rows)
        preferred = [name for name in self.CANDIDATE_TABLES if name in table_names]
        fallback = [
            name
            for name in table_names
            if name not in preferred and not name.startswith("sqlite_")
        ]
        return tuple(preferred + fallback)

    def _table_info(
        self,
        connection: sqlite3.Connection,
        table_name: str,
    ) -> tuple[sqlite3.Row, ...]:
        return tuple(connection.execute(f'PRAGMA table_info("{table_name}")').fetchall())

    def _first_existing(
        self,
        columns: set[str],
        candidates: Sequence[str],
    ) -> str | None:
        for candidate in candidates:
            if candidate in columns:
                return candidate
        return None

    def _iter_explicit_key_rows(
        self,
        connection: sqlite3.Connection,
        table_name: str,
        key_col: str,
    ) -> Iterable[tuple[ItemKey, dict[str, Any]]]:
        query = f'''
            SELECT rowid AS __rowid__, "{key_col}" AS item_key
            FROM "{table_name}"
            WHERE "{key_col}" IS NOT NULL
        '''

        for row in connection.execute(query):
            raw_key = str(row["item_key"]).strip()
            if not raw_key:
                continue

            try:
                item_key = ItemKey.parse(raw_key)
            except ValueError:
                logger.debug(
                    "Skipping invalid DB item key from table=%s rowid=%s: %r",
                    table_name,
                    row["__rowid__"],
                    raw_key,
                )
                continue

            yield item_key, {
                "source": f"db:{table_name}",
                "db_rowid": int(row["__rowid__"]),
            }

    def _iter_composed_key_rows(
        self,
        connection: sqlite3.Connection,
        table_name: str,
        type_col: str,
        language_col: str,
        normalized_col: str,
    ) -> Iterable[tuple[ItemKey, dict[str, Any]]]:
        query = f'''
            SELECT
                rowid AS __rowid__,
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

            if not item_type or not language or not normalized:
                continue

            yield ItemKey(
                item_type=item_type,
                language=language,
                normalized=normalized,
            ), {
                "source": f"db:{table_name}",
                "db_rowid": int(row["__rowid__"]),
            }


class KeyNormalizationAuditService:
    """
    Coordinates audit sources and proposed key normalization.

    This service is intentionally read-only.
    """

    def __init__(self, normalizer: ItemKeyNormalizer | None = None) -> None:
        self.normalizer = normalizer or ItemKeyNormalizer()

    def audit(
        self,
        *,
        vault_path: Path | None = None,
        db_path: Path | None = None,
    ) -> KeyAuditReport:
        records: list[KeyAuditRecord] = []

        sources: list[Any] = []
        if vault_path is not None:
            sources.append(VaultKeyAuditSource(vault_path))
        if db_path is not None:
            sources.append(DatabaseKeyAuditSource(db_path))

        if not sources:
            raise ValueError("At least one source is required: vault_path or db_path.")

        for source in sources:
            for item_key, metadata in source.iter_items():
                proposed_key, result = self.normalizer.normalize_item_key(item_key)

                records.append(
                    KeyAuditRecord(
                        source=str(metadata.get("source", "unknown")),
                        item_key=item_key.render(),
                        proposed_key=proposed_key.render(),
                        item_type=item_key.item_type,
                        language=item_key.language,
                        current_normalized=item_key.normalized,
                        proposed_normalized=proposed_key.normalized,
                        changed=item_key.render() != proposed_key.render(),
                        operations=result.operations,
                        file_path=metadata.get("file_path"),
                        db_rowid=metadata.get("db_rowid"),
                        note_title=metadata.get("note_title"),
                    )
                )

        return KeyAuditReport(
            config=self.normalizer.config,
            records=tuple(records),
            summary=self._summarize(records),
        )

    def _summarize(self, records: Sequence[KeyAuditRecord]) -> KeyAuditSummary:
        changed = [record for record in records if record.changed]

        return KeyAuditSummary(
            total_records=len(records),
            changed_records=len(changed),
            unchanged_records=len(records) - len(changed),
            changed_by_item_type=dict(Counter(record.item_type for record in changed)),
            changed_by_language=dict(Counter(record.language for record in changed)),
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit LanguageOS item keys against a versioned normalization profile.",
    )
    parser.add_argument(
        "--vault",
        type=Path,
        default=None,
        help="Path to the Obsidian vault. Example: D:\\LanguageOS\\Obsidian\\LanguageOS_vault",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Path to languageos.db.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional path to write full JSON audit report.",
    )
    parser.add_argument(
        "--changed-only",
        action="store_true",
        help="Only print records where the proposed key differs from the current key.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of records to print to console.",
    )
    return parser


def run_audit_from_args(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    service = KeyNormalizationAuditService()
    report = service.audit(
        vault_path=args.vault,
        db_path=args.db,
    )

    print("Key Normalization Audit v1")
    print("=" * 80)
    print(f"Profile          : {report.config.profile.value}")
    print(f"Total records    : {report.summary.total_records}")
    print(f"Changed records  : {report.summary.changed_records}")
    print(f"Unchanged records: {report.summary.unchanged_records}")

    if report.summary.changed_by_item_type:
        print(f"Changed by type  : {dict(report.summary.changed_by_item_type)}")
    if report.summary.changed_by_language:
        print(f"Changed by lang  : {dict(report.summary.changed_by_language)}")

    print("-" * 80)

    records = report.changed_records() if args.changed_only else report.records
    for index, record in enumerate(records[: args.limit], start=1):
        marker = "CHANGE" if record.changed else "OK"
        location = record.file_path or (
            f"{record.source} rowid={record.db_rowid}"
            if record.db_rowid is not None
            else record.source
        )

        print(f"[{index}] {marker} {location}")
        print(f"    current : {record.item_key}")
        print(f"    proposed: {record.proposed_key}")
        if record.operations:
            print(f"    ops     : {', '.join(record.operations)}")

    if len(records) > args.limit:
        print(f"... truncated {len(records) - args.limit} records. Use --limit to show more.")

    if args.output_json is not None:
        report.write_json(args.output_json)
        print("-" * 80)
        print(f"JSON report written: {args.output_json}")

    return 1 if report.summary.has_changes else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.vault is None and args.db is None:
        parser.error("At least one of --vault or --db is required.")

    return run_audit_from_args(args)