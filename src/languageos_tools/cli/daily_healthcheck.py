from __future__ import annotations

from typing import Sequence

from languageos_tools.pipeline.daily_healthcheck import main as daily_healthcheck_main


def main(argv: Sequence[str] | None = None) -> int:
    return daily_healthcheck_main(argv)