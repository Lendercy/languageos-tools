from __future__ import annotations

import argparse
import json
from pathlib import Path

from languageos_tools.datastore.relation_repository import (
    RelationRepository,
    RelationRepositoryConfig,
)


CONFIG_PATH = Path("configs/languageos.config.json")


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


def print_relation(row: dict, direction: str) -> None:
    if direction == "outgoing":
        print(f"  --{row['relation_type']}--> {row['target_key']}")
        print(f"    target  : {row['target_path']}")
    else:
        print(f"  <--{row['relation_type']}-- {row['source_key']}")
        print(f"    source  : {row['source_path']}")

    print(f"    evidence: {row['evidence']}")
    print(f"    confidence: {row['confidence']}")


def print_item_summary(item: dict) -> None:
    print(f"- {item['item_key']}")
    print(f"  type    : {item['item_type']}")
    print(f"  language: {item['language']}")
    print(f"  path    : {item['obsidian_path']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Query structured LanguageOS relations from SQLite.",
    )
    parser.add_argument(
        "query",
        help="Item key, normalized text, or path fragment to search relations for.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of matching items to show.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Show relations for all matched items instead of only the first match.",
    )

    args = parser.parse_args()

    config = load_config()
    db_path = resolve_db_path(config)

    repository = RelationRepository(
        RelationRepositoryConfig(
            db_path=db_path,
        )
    )

    matches = repository.search_item_keys(args.query, limit=args.limit)

    print("LanguageOS Relation Query")
    print("=" * 60)
    print(f"Query : {args.query}")
    print(f"DB    : {db_path}")
    print(f"Matches: {len(matches)}")

    if not matches:
        print("\nNo relation items matched this query.")
        print("Try rebuilding the relation index first:")
        print("  python scripts\\rebuild_relation_index.py")
        return

    print("\nMatched Items")
    print("-" * 60)

    for item in matches:
        print_item_summary(item)

    selected_items = matches if args.all else matches[:1]

    print("\nRelations")
    print("-" * 60)

    for item in selected_items:
        item_key = item["item_key"]
        neighbors = repository.get_neighbors(item_key)

        print(f"\n{item_key}")
        print("~" * 60)

        outgoing = neighbors["outgoing"]
        incoming = neighbors["incoming"]

        if not outgoing and not incoming:
            print("  No incoming or outgoing relations.")
            continue

        if outgoing:
            print("  Outgoing:")
            for row in outgoing:
                print_relation(row, direction="outgoing")

        if incoming:
            print("  Incoming:")
            for row in incoming:
                print_relation(row, direction="incoming")


if __name__ == "__main__":
    main()