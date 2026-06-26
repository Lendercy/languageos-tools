from __future__ import annotations

from typing import Sequence

from languageos_tools.validation.schema_validator import main as schema_validation_main


def main(argv: Sequence[str] | None = None) -> int:
    return schema_validation_main(argv)