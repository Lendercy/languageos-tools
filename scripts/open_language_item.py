from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

from languageos_tools.datastore.activity import print_touch_result, touch_by_query


CONFIG_PATH = Path("configs/languageos.config.json")


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_obsidian_uri(note_path: Path) -> str:
    return "obsidian://open?path=" + quote(str(note_path), safe="")


def open_in_obsidian(note_path: Path) -> None:
    uri = build_obsidian_uri(note_path)

    if sys.platform.startswith("win"):
        os.startfile(uri)  # type: ignore[attr-defined]
        return

    print(f"[WARN] Auto-open is currently only supported on Windows.")
    print(f"Open manually: {note_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Open a LanguageOS item and record access activity.",
    )

    parser.add_argument(
        "query",
        help="Item text to open, for example: trotzdem",
    )

    parser.add_argument(
        "--language",
        default=None,
        choices=["english", "german", "mixed", "unknown"],
        help="Optional language filter.",
    )

    parser.add_argument(
        "--type",
        default=None,
        choices=[
            "vocabulary",
            "sentence",
            "grammar",
            "transcript",
            "tts_audio",
            "writing_error",
        ],
        help="Optional item type filter.",
    )

    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Record access but do not open Obsidian.",
    )

    args = parser.parse_args()

    config = load_config()
    vault_root = Path(config["obsidian_vault"])

    payload = touch_by_query(
        query=args.query,
        language=args.language,
        item_type=args.type,
    )

    print_touch_result(payload)

    if payload["matched"] == 0:
        print("\n[INFO] No exact match opened.")
        return

    first_item = payload["touched"][0]
    relative_path = first_item["obsidian_path"]
    note_path = vault_root / relative_path

    print("\nOpen Item")
    print("=" * 60)
    print(f"Path: {note_path}")

    if not note_path.exists():
        print("[WARN] Note path does not exist on disk.")
        print("The DB may be stale. Run:")
        print("python scripts\\build_language_db.py")
        return

    if args.no_open:
        print("[OK] Access recorded. Open skipped because --no-open was used.")
        return

    open_in_obsidian(note_path)
    print("[OK] Opened in Obsidian.")


if __name__ == "__main__":
    main()