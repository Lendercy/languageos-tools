from __future__ import annotations

import argparse
import json
from pathlib import Path

from languageos_tools.migrations.migration_runner import (
    MigrationContext,
    MigrationPlan,
    MigrationRunner,
    MigrationSummaryPrinter,
)
from languageos_tools.migrations.relation_backfill_migration import (
    RelationBackfillMigration,
)
from languageos_tools.obsidian.vault import ObsidianVault
from languageos_tools.obsidian.writer import ObsidianNoteWriter


CONFIG_PATH = Path("configs/languageos.config.json")


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")

    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill generic Relations section from legacy relation sections.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing notes.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Disable backups when writing notes.",
    )
    parser.add_argument(
        "--backfill-version",
        default="1.0",
        help="Backfill version to apply.",
    )
    parser.add_argument(
        "--root",
        action="append",
        default=[],
        help=(
            "Optional vault-relative root to migrate. "
            "Can be passed multiple times. Example: --root Vocabulary --root Sentences"
        ),
    )

    args = parser.parse_args()

    config = load_config()
    languageos_root = Path(config["languageos_root"])
    vault_root = Path(config["obsidian_vault"])

    vault = ObsidianVault(vault_root)
    writer = ObsidianNoteWriter(
        vault=vault,
        backup_root=languageos_root / "Inbox" / "Backups" / "Migrations",
    )

    context = MigrationContext(
        vault=vault,
        writer=writer,
        dry_run=args.dry_run,
        backup=not args.no_backup,
    )

    migration = RelationBackfillMigration(
        backfill_version=args.backfill_version,
    )

    plan = MigrationPlan(
        name=migration.name,
        target_roots=args.root,
    )

    summary = MigrationRunner(context).run(migration, plan=plan)
    MigrationSummaryPrinter().print(summary)


if __name__ == "__main__":
    main()