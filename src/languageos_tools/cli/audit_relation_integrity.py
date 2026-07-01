from __future__ import annotations

from collections.abc import Sequence

from languageos_tools.relations.integrity_audit import main as relation_audit_main


def main(argv: Sequence[str] | None = None) -> int:
    return relation_audit_main(argv)
