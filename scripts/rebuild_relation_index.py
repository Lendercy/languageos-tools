from __future__ import annotations

import argparse
import json
from pathlib import Path

from languageos_tools.datastore.relation_repository import (
    RelationRepository,
    RelationRepositoryConfig,
)
from languageos_tools.obsidian.vault import ObsidianVault
from languageos_tools.relations.parser import (
    RelationMarkdownParser,
    build_relation_parse_context,
)
from languageos_tools.relations.service import RelationService
from languageos_tools.relations.taxonomy import RelationTaxonomy


CONFIG_PATH = Path("configs/languageos.config.json")
RELATION_TAXONOMY_PATH = Path("src/languageos_tools/relations/relation_types.json")


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")

    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def resolve_db_path(config: dict) -> Path:
    languageos_root = Path(config["languageos_root"])
    outputs = config.get("outputs", {})

    return Path(
        outputs.get(
            "languageos_db",
            languageos_root / "Inbox" / "Indexes" / "languageos.db",
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild structured LanguageOS relation index from Obsidian notes.",
    )
    parser.add_argument(
        "--root",
        action="append",
        default=[],
        help=(
            "Optional vault-relative root to parse. "
            "Can be passed multiple times. Example: --root Vocabulary --root Sentences"
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of relations to print.",
    )

    args = parser.parse_args()

    config = load_config()
    vault = ObsidianVault(Path(config["obsidian_vault"]))
    db_path = resolve_db_path(config)

    target_roots = args.root or [None]

    notes = []

    for root in target_roots:
        notes.extend(list(vault.iter_notes(root=root)))

    taxonomy = RelationTaxonomy.load(RELATION_TAXONOMY_PATH)
    relation_service = RelationService(taxonomy)
    relation_parser = RelationMarkdownParser(relation_service)

    context = build_relation_parse_context(notes)

    parsed_relations = []

    for note in notes:
        parsed_relations.extend(
            relation_parser.parse_note(
                note=note,
                context=context,
            )
        )

    repository = RelationRepository(
        RelationRepositoryConfig(
            db_path=db_path,
        )
    )

    inserted_count = repository.rebuild(parsed_relations)

    print("Rebuild LanguageOS Relation Index")
    print("=" * 60)
    print(f"[OK] DB path          : {db_path}")
    print(f"[OK] Parsed notes     : {len(notes)}")
    print(f"[OK] Parsed relations : {len(parsed_relations)}")
    print(f"[OK] Inserted rows    : {inserted_count}")
    print(f"[OK] Stored rows      : {repository.count()}")

    print("\nRelations")
    print("-" * 60)

    for row in repository.list_relations(limit=args.limit):
        print(
            f"{row['source_key']} "
            f"--{row['relation_type']}--> "
            f"{row['target_key']}"
        )
        print(f"  evidence: {row['evidence']}")
        print(f"  source  : {row['source_path']}")
        print(f"  target  : {row['target_path']}")


if __name__ == "__main__":
    main()