from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from languageos_tools.core.normalization import (
    ItemKey,
    ItemKeyExtractor,
    ItemKeyNormalizer,
    MarkdownFrontmatterReader,
    NormalizationConfig,
)


logger = logging.getLogger(__name__)


class KeyNormalizationMigrationError(RuntimeError):
    """Raised when the migration cannot be planned or applied safely."""


@dataclass(frozen=True)
class ItemKeyChange:
    file_path: str
    old_key: str
    new_key: str
    item_type: str
    language: str
    old_normalized: str
    new_normalized: str
    operations: tuple[str, ...]


@dataclass(frozen=True)
class FileAction:
    action_type: str
    detail: str


@dataclass(frozen=True)
class FileMigrationPlan:
    file_path: Path
    relative_path: Path
    old_content: str
    new_content: str
    actions: tuple[FileAction, ...]

    @property
    def changed(self) -> bool:
        return self.old_content != self.new_content


@dataclass(frozen=True)
class KeyNormalizationMigrationReport:
    dry_run: bool
    profile: str
    vault_path: str
    changed_items: tuple[ItemKeyChange, ...]
    changed_files: tuple[str, ...]
    actions: Mapping[str, list[dict[str, str]]]
    backup_root: str | None = None
    backup_batch_path: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "profile": self.profile,
            "vault_path": self.vault_path,
            "backup_root": self.backup_root,
            "backup_batch_path": self.backup_batch_path,
            "summary": {
                "changed_items": len(self.changed_items),
                "changed_files": len(self.changed_files),
            },
            "changed_items": [dataclasses.asdict(change) for change in self.changed_items],
            "changed_files": list(self.changed_files),
            "actions": dict(self.actions),
        }

    def write_json(self, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(self.to_json_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


@dataclass(frozen=True)
class FrontmatterDocument:
    original_text: str
    lines: tuple[str, ...]
    start_index: int
    end_index: int
    data: Mapping[str, Any]

    @classmethod
    def parse(
        cls,
        text: str,
        reader: MarkdownFrontmatterReader,
    ) -> "FrontmatterDocument | None":
        lines = tuple(text.splitlines(keepends=True))

        if not lines:
            return None

        if lines[0].strip() != "---":
            return None

        end_index: int | None = None
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                end_index = index
                break

        if end_index is None:
            return None

        frontmatter_text = "".join(lines[: end_index + 1])
        temp_text = frontmatter_text + "\n"
        data = reader._parse_simple_yaml(  # noqa: SLF001 - controlled internal reuse.
            [line.rstrip("\r\n") for line in lines[1:end_index]]
        )

        _ = temp_text  # Keeps parsing intent explicit for future replacement.

        return cls(
            original_text=text,
            lines=lines,
            start_index=0,
            end_index=end_index,
            data=data,
        )

    def replace_frontmatter_scalar(self, key: str, value: str) -> str:
        updated_lines = list(self.lines)
        key_pattern = re.compile(r"^(\s*)([^:#\s][^:]*?)(\s*:\s*)(.*?)(\r?\n)?$")

        for index in range(self.start_index + 1, self.end_index):
            line = updated_lines[index]
            match = key_pattern.match(line)

            if not match:
                continue

            prefix, raw_key, separator, raw_value, newline = match.groups()
            if raw_key.strip() != key:
                continue

            formatted_value = self._format_scalar_value(value, raw_value)
            updated_lines[index] = f"{prefix}{raw_key}{separator}{formatted_value}{newline or ''}"
            return "".join(updated_lines)

        return self.original_text

    def replace_first_existing_scalar(
        self,
        candidate_keys: Sequence[str],
        value: str,
    ) -> tuple[str, str | None]:
        content = self.original_text

        for key in candidate_keys:
            updated = FrontmatterDocument.parse(
                content,
                MarkdownFrontmatterReader(),
            )

            if updated is None:
                return content, None

            if key not in updated.data:
                continue

            new_content = updated.replace_frontmatter_scalar(key, value)
            if new_content != content:
                return new_content, key

        return content, None

    def _format_scalar_value(self, new_value: str, old_raw_value: str) -> str:
        stripped_old = old_raw_value.strip()

        if len(stripped_old) >= 2 and stripped_old[0] == stripped_old[-1] == '"':
            escaped = new_value.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'

        if len(stripped_old) >= 2 and stripped_old[0] == stripped_old[-1] == "'":
            escaped = new_value.replace("'", "''")
            return f"'{escaped}'"

        return new_value


@dataclass(frozen=True)
class NoteSnapshot:
    path: Path
    relative_path: Path
    content: str
    item_key: ItemKey | None


class KeyNormalizationMigrationService:
    """
    Dry-run/apply migration for LanguageOS item key normalization.

    The migration is intentionally conservative:
    - scans Markdown notes only;
    - computes a complete old_key -> new_key map before writing;
    - validates key collisions before applying;
    - creates per-run backups before any write;
    - performs exact key reference replacement to keep relation blocks consistent;
    - is idempotent after successful apply.
    """

    NORMALIZED_FIELD_CANDIDATES = ("normalized", "normalized_text", "canonical")
    EXPLICIT_KEY_FIELD_CANDIDATES = ("item_key", "key", "id")

    def __init__(
        self,
        *,
        normalizer: ItemKeyNormalizer | None = None,
        frontmatter_reader: MarkdownFrontmatterReader | None = None,
        key_extractor: ItemKeyExtractor | None = None,
    ) -> None:
        self.normalizer = normalizer or ItemKeyNormalizer(NormalizationConfig())
        self.frontmatter_reader = frontmatter_reader or MarkdownFrontmatterReader()
        self.key_extractor = key_extractor or ItemKeyExtractor()

    def dry_run(
        self,
        *,
        vault_path: Path,
        output_json: Path | None = None,
    ) -> KeyNormalizationMigrationReport:
        report = self._run(
            vault_path=vault_path,
            apply=False,
            backup_root=None,
        )

        if output_json is not None:
            report.write_json(output_json)

        return report

    def apply(
        self,
        *,
        vault_path: Path,
        backup_root: Path,
        output_json: Path | None = None,
    ) -> KeyNormalizationMigrationReport:
        report = self._run(
            vault_path=vault_path,
            apply=True,
            backup_root=backup_root,
        )

        if output_json is not None:
            report.write_json(output_json)

        return report

    def _run(
        self,
        *,
        vault_path: Path,
        apply: bool,
        backup_root: Path | None,
    ) -> KeyNormalizationMigrationReport:
        vault_path = vault_path.resolve()

        if not vault_path.exists():
            raise FileNotFoundError(f"Vault path does not exist: {vault_path}")

        if apply and backup_root is None:
            raise KeyNormalizationMigrationError("--backup-root is required when applying.")

        snapshots = self._load_snapshots(vault_path)
        changes = self._compute_item_key_changes(snapshots)
        old_to_new = {change.old_key: change.new_key for change in changes}

        self._validate_key_map(
            snapshots=snapshots,
            changes=changes,
            old_to_new=old_to_new,
        )

        plans = self._build_file_plans(
            snapshots=snapshots,
            old_to_new=old_to_new,
        )

        changed_plans = tuple(plan for plan in plans if plan.changed)
        backup_batch_path: Path | None = None

        if apply and changed_plans:
            assert backup_root is not None
            backup_batch_path = self._backup_and_write(
                plans=changed_plans,
                backup_root=backup_root,
            )

        report = KeyNormalizationMigrationReport(
            dry_run=not apply,
            profile=self.normalizer.config.profile.value,
            vault_path=str(vault_path),
            backup_root=str(backup_root.resolve()) if backup_root is not None else None,
            backup_batch_path=str(backup_batch_path) if backup_batch_path is not None else None,
            changed_items=changes,
            changed_files=tuple(str(plan.file_path) for plan in changed_plans),
            actions={
                str(plan.file_path): [
                    {
                        "action_type": action.action_type,
                        "detail": action.detail,
                    }
                    for action in plan.actions
                ]
                for plan in changed_plans
            },
        )

        return report

    def _load_snapshots(self, vault_path: Path) -> tuple[NoteSnapshot, ...]:
        snapshots: list[NoteSnapshot] = []

        for path in sorted(vault_path.rglob("*.md")):
            content = path.read_text(encoding="utf-8")
            document = FrontmatterDocument.parse(content, self.frontmatter_reader)

            item_key: ItemKey | None = None
            if document is not None:
                item_key = self.key_extractor.extract(document.data)

            snapshots.append(
                NoteSnapshot(
                    path=path,
                    relative_path=path.relative_to(vault_path),
                    content=content,
                    item_key=item_key,
                )
            )

        return tuple(snapshots)

    def _compute_item_key_changes(
        self,
        snapshots: Sequence[NoteSnapshot],
    ) -> tuple[ItemKeyChange, ...]:
        changes: list[ItemKeyChange] = []

        for snapshot in snapshots:
            if snapshot.item_key is None:
                continue

            proposed_key, result = self.normalizer.normalize_item_key(snapshot.item_key)

            old_rendered = snapshot.item_key.render()
            new_rendered = proposed_key.render()

            if old_rendered == new_rendered:
                continue

            changes.append(
                ItemKeyChange(
                    file_path=str(snapshot.path),
                    old_key=old_rendered,
                    new_key=new_rendered,
                    item_type=snapshot.item_key.item_type,
                    language=snapshot.item_key.language,
                    old_normalized=snapshot.item_key.normalized,
                    new_normalized=proposed_key.normalized,
                    operations=result.operations,
                )
            )

        return tuple(changes)

    def _validate_key_map(
        self,
        *,
        snapshots: Sequence[NoteSnapshot],
        changes: Sequence[ItemKeyChange],
        old_to_new: Mapping[str, str],
    ) -> None:
        current_key_to_files: dict[str, list[str]] = defaultdict(list)

        for snapshot in snapshots:
            if snapshot.item_key is None:
                continue
            current_key_to_files[snapshot.item_key.render()].append(str(snapshot.path))

        duplicate_current = {
            key: files
            for key, files in current_key_to_files.items()
            if len(files) > 1
        }
        if duplicate_current:
            raise KeyNormalizationMigrationError(
                "Duplicate current item keys detected. Resolve duplicates before migration: "
                + json.dumps(duplicate_current, ensure_ascii=False, indent=2)
            )

        proposed_key_to_old: dict[str, list[str]] = defaultdict(list)
        for change in changes:
            proposed_key_to_old[change.new_key].append(change.old_key)

        duplicate_proposed = {
            new_key: old_keys
            for new_key, old_keys in proposed_key_to_old.items()
            if len(old_keys) > 1
        }
        if duplicate_proposed:
            raise KeyNormalizationMigrationError(
                "Normalization would merge multiple item keys. Manual review required: "
                + json.dumps(duplicate_proposed, ensure_ascii=False, indent=2)
            )

        changed_old_keys = set(old_to_new.keys())

        for change in changes:
            existing_files = current_key_to_files.get(change.new_key, [])
            if existing_files and change.new_key not in changed_old_keys:
                raise KeyNormalizationMigrationError(
                    "Normalization would collide with an existing unchanged key: "
                    f"{change.old_key!r} -> {change.new_key!r}; existing files={existing_files}"
                )

    def _build_file_plans(
        self,
        *,
        snapshots: Sequence[NoteSnapshot],
        old_to_new: Mapping[str, str],
    ) -> tuple[FileMigrationPlan, ...]:
        plans: list[FileMigrationPlan] = []

        for snapshot in snapshots:
            content = snapshot.content
            actions: list[FileAction] = []

            if snapshot.item_key is not None:
                old_key = snapshot.item_key.render()
                new_key = old_to_new.get(old_key)

                if new_key is not None:
                    proposed_item_key = ItemKey.parse(new_key)

                    content, updated_field = self._update_normalized_frontmatter(
                        content=content,
                        new_normalized=proposed_item_key.normalized,
                    )
                    if updated_field is not None:
                        actions.append(
                            FileAction(
                                action_type="update_frontmatter_normalized",
                                detail=(
                                    f"{updated_field}: "
                                    f"{snapshot.item_key.normalized!r} -> "
                                    f"{proposed_item_key.normalized!r}"
                                ),
                            )
                        )

                    content, updated_key_field = self._update_explicit_key_frontmatter(
                        content=content,
                        new_key=new_key,
                    )
                    if updated_key_field is not None:
                        actions.append(
                            FileAction(
                                action_type="update_frontmatter_item_key",
                                detail=f"{updated_key_field}: {old_key!r} -> {new_key!r}",
                            )
                        )

            for old_key, new_key in old_to_new.items():
                occurrence_count = content.count(old_key)
                if occurrence_count <= 0:
                    continue

                content = content.replace(old_key, new_key)
                actions.append(
                    FileAction(
                        action_type="replace_key_reference",
                        detail=f"{old_key!r} -> {new_key!r}; occurrences={occurrence_count}",
                    )
                )

            plans.append(
                FileMigrationPlan(
                    file_path=snapshot.path,
                    relative_path=snapshot.relative_path,
                    old_content=snapshot.content,
                    new_content=content,
                    actions=tuple(actions),
                )
            )

        return tuple(plans)

    def _update_normalized_frontmatter(
        self,
        *,
        content: str,
        new_normalized: str,
    ) -> tuple[str, str | None]:
        document = FrontmatterDocument.parse(content, self.frontmatter_reader)

        if document is None:
            return content, None

        return document.replace_first_existing_scalar(
            self.NORMALIZED_FIELD_CANDIDATES,
            new_normalized,
        )

    def _update_explicit_key_frontmatter(
        self,
        *,
        content: str,
        new_key: str,
    ) -> tuple[str, str | None]:
        document = FrontmatterDocument.parse(content, self.frontmatter_reader)

        if document is None:
            return content, None

        return document.replace_first_existing_scalar(
            self.EXPLICIT_KEY_FIELD_CANDIDATES,
            new_key,
        )

    def _backup_and_write(
        self,
        *,
        plans: Sequence[FileMigrationPlan],
        backup_root: Path,
    ) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_batch_path = (
            backup_root.resolve()
            / "KeyNormalizationMigration_v1"
            / timestamp
        )

        for plan in plans:
            backup_path = backup_batch_path / plan.relative_path
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            backup_path.write_text(plan.old_content, encoding="utf-8")

        for plan in plans:
            plan.file_path.write_text(plan.new_content, encoding="utf-8")

        return backup_batch_path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate LanguageOS note keys to the key_v1 normalization profile. "
            "Default mode is dry-run."
        )
    )
    parser.add_argument(
        "--vault",
        type=Path,
        required=True,
        help="Path to Obsidian vault.",
    )
    parser.add_argument(
        "--backup-root",
        type=Path,
        default=None,
        help="Backup root. Required with --apply.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional JSON report path.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply migration. Without this flag, the command is dry-run only.",
    )
    return parser


def print_report(report: KeyNormalizationMigrationReport) -> None:
    mode = "DRY-RUN" if report.dry_run else "APPLIED"

    print("Key Normalization Migration v1")
    print("=" * 80)
    print(f"Mode         : {mode}")
    print(f"Profile      : {report.profile}")
    print(f"Vault        : {report.vault_path}")
    print(f"Changed items: {len(report.changed_items)}")
    print(f"Changed files: {len(report.changed_files)}")

    if report.backup_batch_path is not None:
        print(f"Backup batch : {report.backup_batch_path}")

    print("-" * 80)

    if not report.changed_items:
        print("No item key normalization changes required.")
        return

    for index, change in enumerate(report.changed_items, start=1):
        print(f"[{index}] {change.file_path}")
        print(f"    old: {change.old_key}")
        print(f"    new: {change.new_key}")
        if change.operations:
            print(f"    ops: {', '.join(change.operations)}")

    if report.actions:
        print("-" * 80)
        print("File actions:")
        for file_path, actions in report.actions.items():
            print(f"- {file_path}")
            for action in actions:
                print(f"    [{action['action_type']}] {action['detail']}")


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.apply and args.backup_root is None:
        parser.error("--backup-root is required when using --apply.")

    service = KeyNormalizationMigrationService()

    if args.apply:
        report = service.apply(
            vault_path=args.vault,
            backup_root=args.backup_root,
            output_json=args.output_json,
        )
    else:
        report = service.dry_run(
            vault_path=args.vault,
            output_json=args.output_json,
        )

    print_report(report)

    if args.output_json is not None:
        print("-" * 80)
        print(f"JSON report written: {args.output_json}")

    return 0