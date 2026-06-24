from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from languageos_tools.core.models import OperationResult
from languageos_tools.obsidian.note import VaultNote
from languageos_tools.obsidian.vault import ObsidianVault


@dataclass(frozen=True)
class WriteOptions:
    dry_run: bool = False
    backup: bool = True
    create_parent_dirs: bool = True
    overwrite: bool = True


@dataclass
class WriteReport:
    result: OperationResult
    backup_path: Path | None = None


class ObsidianNoteWriter:
    """
    Safe write layer for Obsidian markdown notes.

    Responsibilities:
    - Write notes only through explicit write options.
    - Support dry-run.
    - Create backups before changing existing files.
    - Keep writing policies outside business logic.

    Business services should return desired new VaultNote content.
    This writer decides whether and how to persist it.
    """

    def __init__(self, vault: ObsidianVault, backup_root: Path) -> None:
        self._vault = vault
        self._backup_root = backup_root

    def write_note(
        self,
        note: VaultNote,
        options: WriteOptions | None = None,
    ) -> WriteReport:
        options = options or WriteOptions()

        target_path = self._vault.resolve_path(note.absolute_path)
        exists = target_path.exists()

        if exists and not options.overwrite:
            return WriteReport(
                result=OperationResult(
                    status="skipped",
                    message="Target note already exists and overwrite is disabled.",
                    path=target_path,
                    changed=False,
                )
            )

        old_text = target_path.read_text(encoding="utf-8") if exists else None

        if old_text == note.text:
            return WriteReport(
                result=OperationResult(
                    status="unchanged",
                    message="Note content is unchanged.",
                    path=target_path,
                    changed=False,
                )
            )

        if options.dry_run:
            return WriteReport(
                result=OperationResult(
                    status="would_update" if exists else "would_create",
                    message="Dry-run: note would be updated." if exists else "Dry-run: note would be created.",
                    path=target_path,
                    changed=True,
                )
            )

        backup_path: Path | None = None

        if exists and options.backup:
            backup_path = self.backup_note(target_path)

        if options.create_parent_dirs:
            target_path.parent.mkdir(parents=True, exist_ok=True)

        target_path.write_text(note.text, encoding="utf-8")

        return WriteReport(
            result=OperationResult(
                status="updated" if exists else "created",
                message="Note updated successfully." if exists else "Note created successfully.",
                path=target_path,
                changed=True,
            ),
            backup_path=backup_path,
        )

    def backup_note(self, note_path: Path) -> Path:
        note_path = self._vault.resolve_path(note_path)

        if not note_path.exists():
            raise FileNotFoundError(f"Cannot back up missing note: {note_path}")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        relative_path = note_path.relative_to(self._vault.root)
        backup_path = self._backup_root / timestamp / relative_path

        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_text(note_path.read_text(encoding="utf-8"), encoding="utf-8")

        return backup_path

    def write_text(
        self,
        relative_or_absolute_path: str | Path,
        text: str,
        options: WriteOptions | None = None,
    ) -> WriteReport:
        target_path = self._vault.resolve_path(relative_or_absolute_path)

        note = VaultNote(
            vault_root=self._vault.root,
            absolute_path=target_path,
            text=text,
        )

        return self.write_note(note, options=options)