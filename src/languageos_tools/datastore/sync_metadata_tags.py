from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

CONFIG_PATH = Path("configs/languageos.config.json")


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def parse_scalar_value(value: str):
    value = value.strip()

    if value in {"", "null", "None"}:
        return ""

    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]

    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]

    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [
            parse_scalar_value(part.strip())
            for part in inner.split(",")
            if part.strip()
        ]

    return value


def parse_frontmatter(text: str) -> tuple[dict, str, str, bool]:
    if not text.startswith("---"):
        return {}, "", text, False

    parts = text.split("---", 2)

    if len(parts) < 3:
        return {}, "", text, False

    raw_frontmatter = parts[1].strip("\n")
    body = parts[2].lstrip("\n")

    metadata: dict = {}
    current_list_key: str | None = None

    for raw_line in raw_frontmatter.splitlines():
        line = raw_line.rstrip()

        if not line.strip():
            continue

        stripped = line.strip()

        if stripped.startswith("- ") and current_list_key:
            item = parse_scalar_value(stripped[2:].strip())
            metadata.setdefault(current_list_key, []).append(item)
            continue

        if ":" not in stripped:
            current_list_key = None
            continue

        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()

        if value == "":
            metadata[key] = []
            current_list_key = key
        else:
            metadata[key] = parse_scalar_value(value)
            current_list_key = None

    return metadata, raw_frontmatter, body, True


def ensure_list(value) -> list[str]:
    if value is None:
        return []

    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]

    if isinstance(value, str):
        if not value.strip():
            return []
        return [value.strip()]

    return [str(value).strip()]


def safe_tag(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"\s+", "_", value)
    value = value.replace("+", "plus")
    value = re.sub(r"[^a-z0-9_/\-]", "", value)
    value = re.sub(r"_+", "_", value)
    value = value.strip("_-/")
    return value or "unknown"


def add_tag(tags: list[str], prefix: str, value: str | None) -> None:
    if value is None:
        return

    value = str(value).strip()

    if not value:
        return

    tags.append(f"{prefix}/{safe_tag(value)}")


def build_tags(metadata: dict) -> list[str]:
    tags: list[str] = []

    note_type = str(metadata.get("type") or "").strip()
    language = str(metadata.get("language") or "").strip()
    status = str(metadata.get("status") or "").strip()
    anki_status = str(metadata.get("anki_status") or "none").strip()
    review_status = str(metadata.get("review_status") or "unreviewed").strip()
    review_priority = str(metadata.get("review_priority") or "normal").strip()
    level = str(metadata.get("level") or "").strip()
    source_type = str(metadata.get("source_type") or "").strip()

    add_tag(tags, "los", note_type)
    add_tag(tags, "lang", language)
    add_tag(tags, "status", status)
    add_tag(tags, "anki", anki_status)
    add_tag(tags, "review", review_status)
    add_tag(tags, "priority", review_priority)
    add_tag(tags, "level", level)
    add_tag(tags, "source", source_type)

    for topic in ensure_list(metadata.get("topic")):
        add_tag(tags, "topic", topic)

    for skill in ensure_list(metadata.get("skill")):
        add_tag(tags, "skill", skill)

    return sorted(set(tag for tag in tags if tag))


def is_top_level_key(line: str) -> bool:
    return bool(re.match(r"^[A-Za-z0-9_]+\s*:", line))


def remove_existing_tags_block(raw_frontmatter: str) -> str:
    lines = raw_frontmatter.splitlines()
    output: list[str] = []

    i = 0

    while i < len(lines):
        line = lines[i]

        if re.match(r"^\s*tags\s*:", line):
            i += 1

            while i < len(lines):
                next_line = lines[i]

                if is_top_level_key(next_line):
                    break

                i += 1

            continue

        output.append(line)
        i += 1

    return "\n".join(output).strip("\n")


def append_tags_block(raw_frontmatter: str, tags: list[str]) -> str:
    cleaned = remove_existing_tags_block(raw_frontmatter).rstrip()

    tag_lines = ["tags:"]

    for tag in tags:
        tag_lines.append(f"  - {tag}")

    if cleaned:
        return cleaned + "\n" + "\n".join(tag_lines)

    return "\n".join(tag_lines)


def backup_file(note_path: Path, backup_root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root.mkdir(parents=True, exist_ok=True)

    backup_path = backup_root / f"{note_path.stem}.{timestamp}.tags-sync.bak.md"
    backup_path.write_text(note_path.read_text(encoding="utf-8"), encoding="utf-8")

    return backup_path


def find_markdown_notes(vault_root: Path) -> list[Path]:
    return sorted(
        path for path in vault_root.rglob("*.md") if ".obsidian" not in path.parts
    )


def sync_metadata_tags(dry_run: bool, backup: bool) -> dict:
    config = load_config()
    vault_root = Path(config["obsidian_vault"])
    backup_root = Path(config["languageos_root"]) / "Inbox" / "Backups" / "MetadataTags"

    notes = find_markdown_notes(vault_root)

    totals = {
        "scanned": len(notes),
        "updated": 0,
        "unchanged": 0,
        "skipped": 0,
        "errors": 0,
    }

    results: list[dict] = []

    for note_path in notes:
        try:
            text = note_path.read_text(encoding="utf-8")
            metadata, raw_frontmatter, body, has_frontmatter = parse_frontmatter(text)

            if not has_frontmatter:
                totals["skipped"] += 1
                results.append(
                    {
                        "status": "skipped",
                        "reason": "missing frontmatter",
                        "path": str(note_path),
                    }
                )
                continue

            note_type = str(metadata.get("type") or "").strip()

            if not note_type:
                totals["skipped"] += 1
                results.append(
                    {
                        "status": "skipped",
                        "reason": "missing type",
                        "path": str(note_path),
                    }
                )
                continue

            tags = build_tags(metadata)

            if not tags:
                totals["skipped"] += 1
                results.append(
                    {
                        "status": "skipped",
                        "reason": "no tags generated",
                        "path": str(note_path),
                    }
                )
                continue

            updated_frontmatter = append_tags_block(raw_frontmatter, tags)
            new_text = f"---\n{updated_frontmatter}\n---\n\n{body}"

            if new_text == text:
                totals["unchanged"] += 1
                results.append(
                    {
                        "status": "unchanged",
                        "path": str(note_path),
                    }
                )
                continue

            if not dry_run:
                if backup:
                    backup_file(note_path, backup_root)

                note_path.write_text(new_text, encoding="utf-8")

            totals["updated"] += 1
            results.append(
                {
                    "status": "would_update" if dry_run else "updated",
                    "type": note_type,
                    "tags": tags,
                    "path": str(note_path),
                }
            )

        except Exception as exc:
            totals["errors"] += 1
            results.append(
                {
                    "status": "error",
                    "reason": str(exc),
                    "path": str(note_path),
                }
            )

    return {
        "dry_run": dry_run,
        "backup": backup,
        "vault_root": str(vault_root),
        "totals": totals,
        "results": results,
    }


def print_summary(payload: dict) -> None:
    print("Sync Metadata Tags")
    print("=" * 60)

    if payload["dry_run"]:
        print("[DRY RUN] No notes were changed.")

    print(f"Vault  : {payload['vault_root']}")
    print(f"Backup : {payload['backup']}")

    print("\nSummary")
    print("-" * 60)

    totals = payload["totals"]

    print(f"[OK] Scanned notes : {totals['scanned']}")
    print(f"[OK] Updated notes : {totals['updated']}")
    print(f"[OK] Unchanged     : {totals['unchanged']}")
    print(f"[SKIP] Skipped     : {totals['skipped']}")
    print(f"[ERROR] Errors     : {totals['errors']}")

    print("\nDetails")
    print("-" * 60)

    for result in payload["results"]:
        status = result["status"]
        path = result["path"]

        if status in {"updated", "would_update"}:
            print(f"[{status.upper()}] {path}")
            print(f"  tags: {', '.join(result.get('tags', []))}")
        elif status == "unchanged":
            print(f"[OK] {path}")
        elif status == "skipped":
            print(f"[SKIP] {path} — {result.get('reason')}")
        elif status == "error":
            print(f"[ERROR] {path} — {result.get('reason')}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync metadata fields to Obsidian YAML tags.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without modifying notes.",
    )

    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create backups before modifying notes.",
    )

    args = parser.parse_args()

    payload = sync_metadata_tags(
        dry_run=args.dry_run,
        backup=not args.no_backup,
    )

    print_summary(payload)


if __name__ == "__main__":
    main()
