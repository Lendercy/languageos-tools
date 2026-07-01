from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from languageos_tools.core.models import BatchOperationSummary, OperationResult
from languageos_tools.obsidian.note import VaultNote
from languageos_tools.obsidian.vault import ObsidianVault
from languageos_tools.obsidian.writer import ObsidianNoteWriter, WriteOptions


@dataclass(frozen=True)
class MigrationContext:
    vault: ObsidianVault
    writer: ObsidianNoteWriter
    dry_run: bool
    backup: bool


@dataclass
class MigrationPlan:
    name: str
    target_roots: list[str | Path] = field(default_factory=list)


class NoteMigration(Protocol):
    name: str

    def should_process(self, note: VaultNote) -> bool: ...

    def migrate_note(
        self, note: VaultNote, context: MigrationContext
    ) -> VaultNote | None: ...


class MigrationRunner:
    """
    Generic migration runner for Obsidian notes.

    Responsibilities:
    - Iterate notes safely through ObsidianVault.
    - Ask migration if a note should be processed.
    - Apply migration.
    - Persist through ObsidianNoteWriter.
    - Support dry-run, backup, and summary report.

    Individual migrations should not write files directly.
    """

    def __init__(self, context: MigrationContext) -> None:
        self._context = context

    def run(
        self,
        migration: NoteMigration,
        plan: MigrationPlan | None = None,
    ) -> BatchOperationSummary:
        plan = plan or MigrationPlan(name=migration.name)
        summary = BatchOperationSummary(
            name=plan.name,
            dry_run=self._context.dry_run,
        )

        target_roots = plan.target_roots or [None]

        for target_root in target_roots:
            for note in self._context.vault.iter_notes(root=target_root):
                summary.scanned += 1

                try:
                    if not migration.should_process(note):
                        summary.add_result(
                            OperationResult(
                                status="skipped",
                                message="Migration chose not to process this note.",
                                path=note.absolute_path,
                                changed=False,
                            )
                        )
                        continue

                    migrated_note = migration.migrate_note(note, self._context)

                    if migrated_note is None:
                        summary.add_result(
                            OperationResult(
                                status="unchanged",
                                message="Migration produced no changes.",
                                path=note.absolute_path,
                                changed=False,
                            )
                        )
                        continue

                    report = self._context.writer.write_note(
                        migrated_note,
                        options=WriteOptions(
                            dry_run=self._context.dry_run,
                            backup=self._context.backup,
                            create_parent_dirs=True,
                            overwrite=True,
                        ),
                    )

                    summary.add_result(report.result)

                except Exception as exc:
                    summary.add_result(
                        OperationResult(
                            status="error",
                            message=str(exc),
                            path=note.absolute_path,
                            changed=False,
                        )
                    )

        return summary


class MigrationSummaryPrinter:
    def print(self, summary: BatchOperationSummary) -> None:
        print(summary.name)
        print("=" * 60)

        if summary.dry_run:
            print("[DRY RUN] No notes were changed.")

        print("\nSummary")
        print("-" * 60)
        print(f"[OK] Scanned   : {summary.scanned}")
        print(f"[OK] Updated   : {summary.updated}")
        print(f"[OK] Unchanged : {summary.unchanged}")
        print(f"[SKIP] Skipped : {summary.skipped}")
        print(f"[ERROR] Errors : {summary.errors}")

        print("\nDetails")
        print("-" * 60)

        for result in summary.results:
            path_text = str(result.path) if result.path else ""

            if result.status in {"updated", "created", "would_update", "would_create"}:
                print(f"[{result.status.upper()}] {path_text}")
                print(f"  {result.message}")
            elif result.status == "unchanged":
                print(f"[OK] {path_text}")
            elif result.status == "skipped":
                print(f"[SKIP] {path_text} — {result.message}")
            elif result.status == "error":
                print(f"[ERROR] {path_text} — {result.message}")
            else:
                print(f"[{result.status.upper()}] {path_text} — {result.message}")
