from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from languageos_tools.obsidian.note import VaultNote


@dataclass(frozen=True)
class ObsidianVault:
    """
    Read-only access layer for an Obsidian vault.

    Responsibilities:
    - Resolve vault-relative paths safely.
    - Read notes.
    - List markdown notes.
    - Exclude internal Obsidian files when requested.

    Writing and backup are handled by ObsidianNoteWriter.
    """

    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root.resolve())

    def ensure_exists(self) -> None:
        if not self.root.exists():
            raise FileNotFoundError(f"Obsidian vault not found: {self.root}")

        if not self.root.is_dir():
            raise NotADirectoryError(
                f"Obsidian vault path is not a directory: {self.root}"
            )

    def resolve_path(self, relative_or_absolute_path: str | Path) -> Path:
        path = Path(relative_or_absolute_path)

        if path.is_absolute():
            resolved = path.resolve()
        else:
            resolved = (self.root / path).resolve()

        self._ensure_inside_vault(resolved)

        return resolved

    def read_note(self, relative_or_absolute_path: str | Path) -> VaultNote:
        self.ensure_exists()

        note_path = self.resolve_path(relative_or_absolute_path)

        if not note_path.exists():
            raise FileNotFoundError(f"Note not found: {note_path}")

        if not note_path.is_file():
            raise IsADirectoryError(f"Note path is not a file: {note_path}")

        text = note_path.read_text(encoding="utf-8")

        return VaultNote(
            vault_root=self.root,
            absolute_path=note_path,
            text=text,
        )

    def try_read_note(self, relative_or_absolute_path: str | Path) -> VaultNote | None:
        try:
            return self.read_note(relative_or_absolute_path)
        except FileNotFoundError:
            return None

    def list_markdown_files(
        self,
        root: str | Path | None = None,
        include_obsidian_internal: bool = False,
    ) -> list[Path]:
        self.ensure_exists()

        search_root = self.resolve_path(root) if root else self.root

        if not search_root.exists():
            return []

        if search_root.is_file():
            if search_root.suffix.lower() == ".md":
                return [search_root]
            return []

        files: list[Path] = []

        for path in sorted(search_root.rglob("*.md")):
            if not include_obsidian_internal and self._is_obsidian_internal_path(path):
                continue

            files.append(path.resolve())

        return files

    def iter_notes(
        self,
        root: str | Path | None = None,
        include_obsidian_internal: bool = False,
    ) -> Iterable[VaultNote]:
        for path in self.list_markdown_files(
            root=root,
            include_obsidian_internal=include_obsidian_internal,
        ):
            yield self.read_note(path)

    def note_exists(self, relative_or_absolute_path: str | Path) -> bool:
        path = self.resolve_path(relative_or_absolute_path)
        return path.exists() and path.is_file()

    def to_obsidian_path(self, relative_or_absolute_path: str | Path) -> str:
        path = self.resolve_path(relative_or_absolute_path)
        rel = path.relative_to(self.root).as_posix()

        if rel.endswith(".md"):
            return rel[:-3]

        return rel

    def _ensure_inside_vault(self, path: Path) -> None:
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(
                f"Path is outside the Obsidian vault. path={path}, vault={self.root}"
            ) from exc

    def _is_obsidian_internal_path(self, path: Path) -> bool:
        try:
            rel_parts = path.relative_to(self.root).parts
        except ValueError:
            return False

        return ".obsidian" in rel_parts
