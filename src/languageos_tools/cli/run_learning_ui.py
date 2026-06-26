from __future__ import annotations

from typing import Sequence

from languageos_tools.ui.learning_app import main as learning_ui_main


def main(argv: Sequence[str] | None = None) -> int:
    return learning_ui_main(argv)