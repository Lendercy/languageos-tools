from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from languageos_tools.core.frontmatter import FrontmatterParser
from languageos_tools.core.models import FrontmatterDocument


@dataclass
class VaultNote:
    """
    Represents a markdown note inside an Obsidian vault.

    This class is intentionally lightweight:
    - It knows its absolute path and vault-relative path.
    - It can parse and render frontmatter.
    - It does not decide backup/write policies. That belongs to writer.py.
    """

    vault_root: Path
    absolute_path: Path
    text: str

    @property
    def relative_path(self) -> Path:
        return self.absolute_path.relative_to(self.vault_root)

    @property
    def relative_path_posix(self) -> str:
        return self.relative_path.as_posix()

    @property
    def obsidian_path(self) -> str:
        path = self.relative_path_posix

        if path.endswith(".md"):
            return path[:-3]

        return path

    @property
    def title(self) -> str:
        return self.absolute_path.stem

    @property
    def exists(self) -> bool:
        return self.absolute_path.exists()

    def obsidian_link(self, display: str | None = None) -> str:
        label = display or self.title
        return f"[[{self.obsidian_path}|{label}]]"

    def parse(self, parser: FrontmatterParser | None = None) -> FrontmatterDocument:
        parser = parser or FrontmatterParser()
        return parser.parse(self.text)

    def metadata(self, parser: FrontmatterParser | None = None) -> dict[str, Any]:
        return self.parse(parser).metadata

    def body(self, parser: FrontmatterParser | None = None) -> str:
        return self.parse(parser).body

    def with_document(
        self,
        document: FrontmatterDocument,
        parser: FrontmatterParser | None = None,
    ) -> VaultNote:
        parser = parser or FrontmatterParser()
        new_text = parser.render(document)

        return VaultNote(
            vault_root=self.vault_root,
            absolute_path=self.absolute_path,
            text=new_text,
        )

    def with_text(self, text: str) -> VaultNote:
        return VaultNote(
            vault_root=self.vault_root,
            absolute_path=self.absolute_path,
            text=text,
        )
