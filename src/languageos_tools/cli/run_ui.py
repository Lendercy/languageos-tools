from __future__ import annotations

from collections.abc import Sequence

from languageos_tools.ui.app import main as ui_main


def main(argv: Sequence[str] | None = None) -> int:
    return ui_main(argv)
