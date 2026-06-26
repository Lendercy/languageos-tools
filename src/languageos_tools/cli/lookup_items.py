from __future__ import annotations

from typing import Sequence

from languageos_tools.search.lookup_service import main as lookup_main


def main(argv: Sequence[str] | None = None) -> int:
    return lookup_main(argv)