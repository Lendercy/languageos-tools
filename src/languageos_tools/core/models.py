from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from languageos_tools.core.enums import (
    AnkiStatus,
    ItemType,
    LanguageCode,
    LearningStatus,
    RelationType,
    ReviewPriority,
    ReviewStatus,
)


DEFAULT_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class LanguageOSPaths:
    languageos_root: Path
    obsidian_vault: Path
    languageos_db: Path

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "LanguageOSPaths":
        outputs = config.get("outputs", {})

        languageos_root = Path(config["languageos_root"])
        obsidian_vault = Path(config["obsidian_vault"])
        languageos_db = Path(
            outputs.get(
                "languageos_db",
                languageos_root / "Inbox" / "Indexes" / "languageos.db",
            )
        )

        return cls(
            languageos_root=languageos_root,
            obsidian_vault=obsidian_vault,
            languageos_db=languageos_db,
        )


@dataclass
class FrontmatterDocument:
    metadata: dict[str, Any]
    body: str
    has_frontmatter: bool = True

    def get_str(self, key: str, default: str = "") -> str:
        value = self.metadata.get(key, default)

        if value is None:
            return default

        text = str(value).strip()

        return text if text else default

    def get_list(self, key: str) -> list[str]:
        value = self.metadata.get(key)

        if value is None:
            return []

        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]

        if isinstance(value, str):
            text = value.strip()

            if not text:
                return []

            return [text]

        return [str(value).strip()]


@dataclass(frozen=True)
class LanguageItemKey:
    item_type: str
    language: str
    normalized: str

    def as_string(self) -> str:
        return f"{self.item_type}|{self.language}|{self.normalized}"


@dataclass
class LanguageItem:
    key: LanguageItemKey
    title: str
    obsidian_path: str
    absolute_path: Path
    item_type: ItemType = ItemType.UNKNOWN
    language: LanguageCode = LanguageCode.UNKNOWN
    status: LearningStatus = LearningStatus.UNKNOWN
    anki_status: AnkiStatus = AnkiStatus.NONE
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    review_priority: ReviewPriority = ReviewPriority.NORMAL
    schema_version: str = DEFAULT_SCHEMA_VERSION
    topics: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    level: str = "unknown"
    source_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def obsidian_link(self, display: str | None = None) -> str:
        label = display or self.title
        return f"[[{self.obsidian_path}|{label}]]"


@dataclass
class ItemRelation:
    source_key: LanguageItemKey
    target_key: LanguageItemKey
    relation_type: RelationType
    confidence: float = 1.0
    created_by: str = "system"
    created_at: datetime = field(default_factory=datetime.now)
    evidence: str = ""

    def validate(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Relation confidence must be between 0.0 and 1.0.")


@dataclass
class OperationResult:
    status: str
    message: str
    path: Path | None = None
    changed: bool = False
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class BatchOperationSummary:
    name: str
    dry_run: bool
    scanned: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    errors: int = 0
    results: list[OperationResult] = field(default_factory=list)

    def add_result(self, result: OperationResult) -> None:
        self.results.append(result)

        if result.status == "updated" or result.status == "would_update":
            self.updated += 1
        elif result.status == "unchanged":
            self.unchanged += 1
        elif result.status == "skipped":
            self.skipped += 1
        elif result.status == "error":
            self.errors += 1