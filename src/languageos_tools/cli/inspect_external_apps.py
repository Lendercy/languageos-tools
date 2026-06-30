from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from languageos_tools.integrations.external_apps import (
    ExternalAppConfig,
    ExternalAppService,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect LanguageOS external app integrations.",
    )
    parser.add_argument(
        "--vault",
        type=Path,
        default=Path(r"D:\LanguageOS\Obsidian\LanguageOS_vault"),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/local_apps.json"),
    )
    parser.add_argument(
        "--note",
        type=Path,
        default=None,
        help="Optional note file path to build an Obsidian URI for.",
    )
    parser.add_argument(
        "--check-anki",
        action="store_true",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    config = ExternalAppConfig.load(
        vault_path=args.vault,
        config_path=args.config,
    )
    service = ExternalAppService(config)

    print("LanguageOS External Apps")
    print("=" * 80)
    print(f"Vault path          : {config.vault_path}")
    print(f"Obsidian vault name : {config.obsidian_vault_name}")
    print(f"Anki executable     : {config.anki_executable or '(auto)'}")
    print(f"AnkiConnect URL     : {config.anki_connect_url}")

    if args.note is not None:
        print("-" * 80)
        print("Obsidian URI")
        print(service.build_obsidian_uri(args.note))

    if args.check_anki:
        print("-" * 80)
        status = service.check_anki_connect()
        print(status.message)

    return 0