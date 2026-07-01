from __future__ import annotations

import argparse
import dataclasses
import json
import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from languageos_tools.core.key_policy import KeyPolicyRegistry
from languageos_tools.core.normalization import (
    ItemKey,
    ItemKeyNormalizer,
    MarkdownFrontmatterReader,
)
from languageos_tools.core.note_type_registry import (
    NoteTypeDefinition,
    NoteTypeRegistry,
    NoteTypeRegistryError,
)

logger = logging.getLogger(__name__)


class ValidationSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class SchemaValidationIssue:
    severity: ValidationSeverity
    code: str
    message: str
    file_path: str
    field: str | None = None
    expected: str | None = None
    actual: str | None = None


@dataclass(frozen=True)
class ValidatedNote:
    file_path: str
    relative_path: str
    note_type: str | None
    language: str | None
    valid: bool
    issue_count: int


@dataclass(frozen=True)
class SchemaValidationSummary:
    total_markdown_files: int
    validated_notes: int
    skipped_notes: int
    error_count: int
    warning_count: int
    info_count: int
    issues_by_code: Mapping[str, int]
    notes_by_type: Mapping[str, int]
    notes_by_language: Mapping[str, int]

    @property
    def has_errors(self) -> bool:
        return self.error_count > 0


@dataclass(frozen=True)
class SchemaValidationReport:
    vault_path: str
    note_type_registry_path: str
    key_policy_registry_path: str
    summary: SchemaValidationSummary
    notes: tuple[ValidatedNote, ...]
    issues: tuple[SchemaValidationIssue, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "vault_path": self.vault_path,
            "note_type_registry_path": self.note_type_registry_path,
            "key_policy_registry_path": self.key_policy_registry_path,
            "summary": dataclasses.asdict(self.summary),
            "notes": [dataclasses.asdict(note) for note in self.notes],
            "issues": [
                {
                    **dataclasses.asdict(issue),
                    "severity": issue.severity.value,
                }
                for issue in self.issues
            ],
        }

    def write_json(self, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(self.to_json_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


@dataclass(frozen=True)
class MarkdownNoteDocument:
    path: Path
    relative_path: Path
    content: str
    frontmatter: Mapping[str, Any]
    has_frontmatter: bool


class SchemaValidationService:
    """
    Read-only schema validator for LanguageOS Obsidian notes.

    Important behavior:
    - no mutation;
    - note type rules come from NoteTypeRegistry;
    - key normalization rules come from KeyPolicyRegistry;
    - language is required only when the active note type says it is required.
    """

    TYPE_FIELDS = ("type", "item_type", "note_type")
    LANGUAGE_FIELDS = ("language", "lang")
    NORMALIZED_FIELDS = ("normalized", "normalized_text", "canonical")

    def __init__(
        self,
        *,
        note_type_registry: NoteTypeRegistry,
        key_policy_registry: KeyPolicyRegistry,
        note_type_registry_path: Path,
        key_policy_registry_path: Path,
        frontmatter_reader: MarkdownFrontmatterReader | None = None,
    ) -> None:
        self.note_type_registry = note_type_registry
        self.key_policy_registry = key_policy_registry
        self.note_type_registry_path = note_type_registry_path
        self.key_policy_registry_path = key_policy_registry_path
        self.frontmatter_reader = frontmatter_reader or MarkdownFrontmatterReader()
        self.normalizer = ItemKeyNormalizer(
            self.key_policy_registry.to_normalization_config()
        )

    @classmethod
    def from_paths(
        cls,
        *,
        note_type_registry_path: Path,
        key_policy_registry_path: Path,
    ) -> SchemaValidationService:
        return cls(
            note_type_registry=NoteTypeRegistry.load(note_type_registry_path),
            key_policy_registry=KeyPolicyRegistry.load(key_policy_registry_path),
            note_type_registry_path=note_type_registry_path,
            key_policy_registry_path=key_policy_registry_path,
        )

    def validate_vault(
        self,
        *,
        vault_path: Path,
        include_untyped_notes: bool = False,
    ) -> SchemaValidationReport:
        vault_path = vault_path.resolve()
        if not vault_path.exists():
            raise FileNotFoundError(f"Vault path does not exist: {vault_path}")

        documents = self._load_documents(vault_path)
        all_issues: list[SchemaValidationIssue] = []
        validated_notes: list[ValidatedNote] = []
        skipped_count = 0

        for document in documents:
            note_type = self._first_str(document.frontmatter, self.TYPE_FIELDS)
            language = self._first_str(document.frontmatter, self.LANGUAGE_FIELDS)

            if not note_type and not include_untyped_notes:
                skipped_count += 1
                continue

            issues = self._validate_document(document)
            all_issues.extend(issues)

            error_count = sum(
                1 for issue in issues if issue.severity == ValidationSeverity.ERROR
            )

            validated_notes.append(
                ValidatedNote(
                    file_path=str(document.path),
                    relative_path=str(document.relative_path).replace("\\", "/"),
                    note_type=note_type,
                    language=language,
                    valid=error_count == 0,
                    issue_count=len(issues),
                )
            )

        return SchemaValidationReport(
            vault_path=str(vault_path),
            note_type_registry_path=str(self.note_type_registry_path),
            key_policy_registry_path=str(self.key_policy_registry_path),
            summary=self._summarize(
                documents=documents,
                notes=validated_notes,
                issues=all_issues,
                skipped_count=skipped_count,
            ),
            notes=tuple(validated_notes),
            issues=tuple(all_issues),
        )

    def _load_documents(self, vault_path: Path) -> tuple[MarkdownNoteDocument, ...]:
        documents: list[MarkdownNoteDocument] = []

        for path in sorted(vault_path.rglob("*.md")):
            content = path.read_text(encoding="utf-8")
            frontmatter = self.frontmatter_reader.read_frontmatter(path)
            has_frontmatter = content.lstrip().startswith("---")

            documents.append(
                MarkdownNoteDocument(
                    path=path,
                    relative_path=path.relative_to(vault_path),
                    content=content,
                    frontmatter=frontmatter,
                    has_frontmatter=has_frontmatter,
                )
            )

        return tuple(documents)

    def _validate_document(
        self,
        document: MarkdownNoteDocument,
    ) -> tuple[SchemaValidationIssue, ...]:
        issues: list[SchemaValidationIssue] = []

        if not document.has_frontmatter:
            issues.append(
                self._issue(
                    severity=ValidationSeverity.ERROR,
                    code="missing_frontmatter",
                    message="Markdown note is missing YAML frontmatter.",
                    document=document,
                )
            )
            return tuple(issues)

        note_type = self._first_str(document.frontmatter, self.TYPE_FIELDS)
        if not note_type:
            issues.append(
                self._issue(
                    severity=ValidationSeverity.ERROR,
                    code="missing_note_type",
                    message="Missing note type field.",
                    document=document,
                    field="type",
                )
            )
            return tuple(issues)

        normalized_note_type = note_type.strip().casefold()
        if not self.note_type_registry.has(normalized_note_type):
            issues.append(
                self._issue(
                    severity=ValidationSeverity.ERROR,
                    code="unknown_note_type",
                    message=f"Unknown note type: {normalized_note_type!r}.",
                    document=document,
                    field="type",
                    expected=", ".join(self.note_type_registry.list_names()),
                    actual=note_type,
                )
            )
            return tuple(issues)

        definition = self.note_type_registry.get(normalized_note_type)

        issues.extend(
            self._validate_required_frontmatter(
                document=document,
                definition=definition,
            )
        )
        issues.extend(
            self._validate_language(
                document=document,
                definition=definition,
            )
        )
        issues.extend(
            self._validate_normalized_key(
                document=document,
                definition=definition,
            )
        )
        issues.extend(
            self._validate_folder_location(
                document=document,
                definition=definition,
            )
        )

        return tuple(issues)

    def _validate_required_frontmatter(
        self,
        *,
        document: MarkdownNoteDocument,
        definition: NoteTypeDefinition,
    ) -> tuple[SchemaValidationIssue, ...]:
        issues: list[SchemaValidationIssue] = []

        for field in definition.required_frontmatter:
            value = document.frontmatter.get(field)

            if value is None or str(value).strip() == "":
                issues.append(
                    self._issue(
                        severity=ValidationSeverity.ERROR,
                        code="missing_required_frontmatter",
                        message=(
                            f"Missing required frontmatter field {field!r} "
                            f"for note type {definition.name!r}."
                        ),
                        document=document,
                        field=field,
                    )
                )

        return tuple(issues)

    def _validate_language(
        self,
        *,
        document: MarkdownNoteDocument,
        definition: NoteTypeDefinition,
    ) -> tuple[SchemaValidationIssue, ...]:
        language = self._first_str(document.frontmatter, self.LANGUAGE_FIELDS)
        language_required = any(
            field in definition.required_frontmatter for field in self.LANGUAGE_FIELDS
        )

        if not language:
            if language_required:
                return (
                    self._issue(
                        severity=ValidationSeverity.ERROR,
                        code="missing_language",
                        message="Missing language field.",
                        document=document,
                        field="language",
                    ),
                )

            return ()

        normalized_language = language.strip().casefold()
        if not self.note_type_registry.supports_language(normalized_language):
            return (
                self._issue(
                    severity=ValidationSeverity.ERROR,
                    code="unsupported_language",
                    message=f"Unsupported language: {normalized_language!r}.",
                    document=document,
                    field="language",
                    expected=", ".join(self.note_type_registry.supported_languages()),
                    actual=language,
                ),
            )

        if definition.folder_for_language(normalized_language) is None:
            return (
                self._issue(
                    severity=ValidationSeverity.WARNING,
                    code="missing_default_folder_for_language",
                    message=(
                        f"Note type {definition.name!r} has no default folder "
                        f"for language {normalized_language!r}."
                    ),
                    document=document,
                    field="language",
                    actual=language,
                ),
            )

        return ()

    def _validate_normalized_key(
        self,
        *,
        document: MarkdownNoteDocument,
        definition: NoteTypeDefinition,
    ) -> tuple[SchemaValidationIssue, ...]:
        language = self._first_str(document.frontmatter, self.LANGUAGE_FIELDS)
        normalized = self._first_str(document.frontmatter, self.NORMALIZED_FIELDS)

        if not language or not normalized:
            return ()

        current_key = ItemKey(
            item_type=definition.key_policy_item_type,
            language=language,
            normalized=normalized,
        )
        proposed_key, _ = self.normalizer.normalize_item_key(current_key)

        if current_key.render() == proposed_key.render():
            return ()

        return (
            self._issue(
                severity=ValidationSeverity.ERROR,
                code="normalized_key_mismatch",
                message=(
                    "Frontmatter normalized value does not match active key policy."
                ),
                document=document,
                field="normalized",
                expected=proposed_key.normalized,
                actual=normalized,
            ),
        )

    def _validate_folder_location(
        self,
        *,
        document: MarkdownNoteDocument,
        definition: NoteTypeDefinition,
    ) -> tuple[SchemaValidationIssue, ...]:
        language = self._first_str(document.frontmatter, self.LANGUAGE_FIELDS)

        if not language:
            return ()

        expected_folder = definition.folder_for_language(language)
        if not expected_folder:
            return ()

        relative_path = str(document.relative_path).replace("\\", "/")
        normalized_expected_folder = expected_folder.strip("/")

        if relative_path.startswith(normalized_expected_folder + "/"):
            return ()

        return (
            self._issue(
                severity=ValidationSeverity.WARNING,
                code="folder_mismatch",
                message=(
                    "Note path does not match default folder for its note type "
                    "and language."
                ),
                document=document,
                field="path",
                expected=normalized_expected_folder + "/...",
                actual=relative_path,
            ),
        )

    def _summarize(
        self,
        *,
        documents: Sequence[MarkdownNoteDocument],
        notes: Sequence[ValidatedNote],
        issues: Sequence[SchemaValidationIssue],
        skipped_count: int,
    ) -> SchemaValidationSummary:
        severity_counter = Counter(issue.severity for issue in issues)
        code_counter = Counter(issue.code for issue in issues)
        type_counter = Counter(
            note.note_type for note in notes if note.note_type is not None
        )
        language_counter = Counter(
            note.language for note in notes if note.language is not None
        )

        return SchemaValidationSummary(
            total_markdown_files=len(documents),
            validated_notes=len(notes),
            skipped_notes=skipped_count,
            error_count=severity_counter[ValidationSeverity.ERROR],
            warning_count=severity_counter[ValidationSeverity.WARNING],
            info_count=severity_counter[ValidationSeverity.INFO],
            issues_by_code=dict(code_counter),
            notes_by_type=dict(type_counter),
            notes_by_language=dict(language_counter),
        )

    def _first_str(
        self,
        frontmatter: Mapping[str, Any],
        fields: Sequence[str],
    ) -> str | None:
        for field in fields:
            value = frontmatter.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _issue(
        self,
        *,
        severity: ValidationSeverity,
        code: str,
        message: str,
        document: MarkdownNoteDocument,
        field: str | None = None,
        expected: str | None = None,
        actual: str | None = None,
    ) -> SchemaValidationIssue:
        return SchemaValidationIssue(
            severity=severity,
            code=code,
            message=message,
            file_path=str(document.path),
            field=field,
            expected=expected,
            actual=actual,
        )


def build_arg_parser() -> argparse.ArgumentParser:
    project_root = Path(__file__).resolve().parents[3]

    parser = argparse.ArgumentParser(
        description="Validate LanguageOS Obsidian notes against note type registry.",
    )
    parser.add_argument(
        "--vault",
        type=Path,
        required=True,
        help="Path to Obsidian vault.",
    )
    parser.add_argument(
        "--note-types",
        type=Path,
        default=project_root / "configs" / "note_types.json",
        help="Path to note type registry JSON.",
    )
    parser.add_argument(
        "--key-policies",
        type=Path,
        default=project_root / "configs" / "key_policies.json",
        help="Path to key policy registry JSON.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional JSON report path.",
    )
    parser.add_argument(
        "--include-untyped-notes",
        action="store_true",
        help="Also validate Markdown notes without a type field.",
    )
    parser.add_argument(
        "--no-fail-on-error",
        action="store_true",
        help="Return exit code 0 even when validation errors are found.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of issues to print.",
    )
    return parser


def print_report(report: SchemaValidationReport, *, limit: int) -> None:
    print("LanguageOS Schema Validation v1")
    print("=" * 80)
    print(f"Vault files     : {report.summary.total_markdown_files}")
    print(f"Validated notes : {report.summary.validated_notes}")
    print(f"Skipped notes   : {report.summary.skipped_notes}")
    print(f"Errors          : {report.summary.error_count}")
    print(f"Warnings        : {report.summary.warning_count}")
    print(f"Info            : {report.summary.info_count}")

    if report.summary.notes_by_type:
        print(f"Notes by type   : {dict(report.summary.notes_by_type)}")
    if report.summary.notes_by_language:
        print(f"Notes by lang   : {dict(report.summary.notes_by_language)}")
    if report.summary.issues_by_code:
        print(f"Issues by code  : {dict(report.summary.issues_by_code)}")

    print("-" * 80)

    if not report.issues:
        print("No schema validation issues found.")
        return

    for index, issue in enumerate(report.issues[:limit], start=1):
        print(f"[{index}] {issue.severity.value.upper()} {issue.code}")
        print(f"    file    : {issue.file_path}")
        print(f"    message : {issue.message}")

        if issue.field is not None:
            print(f"    field   : {issue.field}")
        if issue.expected is not None:
            print(f"    expected: {issue.expected}")
        if issue.actual is not None:
            print(f"    actual  : {issue.actual}")

    if len(report.issues) > limit:
        print(
            f"... truncated {len(report.issues) - limit} issues. Use --limit to show more."
        )


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        service = SchemaValidationService.from_paths(
            note_type_registry_path=args.note_types,
            key_policy_registry_path=args.key_policies,
        )
    except NoteTypeRegistryError as exc:
        parser.error(str(exc))

    report = service.validate_vault(
        vault_path=args.vault,
        include_untyped_notes=args.include_untyped_notes,
    )

    print_report(report, limit=args.limit)

    if args.output_json is not None:
        report.write_json(args.output_json)
        print("-" * 80)
        print(f"JSON report written: {args.output_json}")

    if report.summary.has_errors and not args.no_fail_on_error:
        return 1

    return 0
