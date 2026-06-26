from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from languageos_tools.core.note_type_registry import (
    NoteTypeRegistry,
    describe_registry,
)


def build_arg_parser() -> argparse.ArgumentParser:
    project_root = Path(__file__).resolve().parents[3]

    parser = argparse.ArgumentParser(
        description="Inspect LanguageOS note type registry.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=project_root / "configs" / "note_types.json",
        help="Path to note type registry JSON.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    registry = NoteTypeRegistry.load(args.config)
    print(describe_registry(registry))

    return 0