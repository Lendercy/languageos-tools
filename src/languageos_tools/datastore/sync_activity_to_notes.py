from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path


CONFIG_PATH = Path("configs/languageos.config.json")


SYNC_FIELDS = {
    "access_count",
    "last_accessed_at",
    "last_reviewed_at",
    "review_status",
    "review_priority",
    "stale_after_days",
}


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_db_path(config: dict) -> Path:
    db_path = config.get("outputs", {}).get("languageos_db")

    if db_path:
        return Path(db_path)

    return Path(config["languageos_root"]) / "Inbox" / "Indexes" / "languageos.db"


def connect_db(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(
            f"LanguageOS database not found: {db_path}\n"
            "Run: python scripts\\build_language_db.py"
        )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    return conn


def split_frontmatter(text: str) -> tuple[str, str, bool]:
    if not text.startswith("---"):
        return "", text, False

    parts = text.split("---", 2)

    if len(parts) < 3:
        return "", text, False

    raw_frontmatter = parts[1].strip("\n")
    body = parts[2].lstrip("\n")

    return raw_frontmatter, body, True


def stringify_value(value) -> str:
    if value is None:
        return ""

    return str(value)


def update_frontmatter(raw_frontmatter: str, updates: dict[str, str]) -> str:
    lines = raw_frontmatter.splitlines()
    remaining = dict(updates)
    output_lines: list[str] = []

    for line in lines:
        match = re.match(r"^(\s*)([A-Za-z0-9_]+)(\s*:\s*)(.*)$", line)

        if not match:
            output_lines.append(line)
            continue

        indent, key, _sep, _old_value = match.groups()

        if key in remaining:
            value = remaining.pop(key)

            # Important:
            # Always write "key: value", not "key:value".
            # Obsidian/YAML can fail to parse frontmatter if the space is missing.
            if value == "":
                output_lines.append(f"{indent}{key}:")
            else:
                output_lines.append(f"{indent}{key}: {value}")
        else:
            output_lines.append(line)

    for key, value in remaining.items():
        if value == "":
            output_lines.append(f"{key}:")
        else:
            output_lines.append(f"{key}: {value}")

    return "\n".join(output_lines)


def backup_file(note_path: Path, backup_root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root.mkdir(parents=True, exist_ok=True)

    backup_path = backup_root / f"{note_path.stem}.{timestamp}.activity-sync.bak.md"
    backup_path.write_text(note_path.read_text(encoding="utf-8"), encoding="utf-8")

    return backup_path


def get_activity_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT
                i.type,
                i.language,
                i.normalized,
                i.text,
                i.obsidian_path,
                i.obsidian_link,

                COALESCE(a.access_count, 0) AS access_count,
                a.last_accessed_at,
                a.last_reviewed_at,
                COALESCE(a.review_status, 'unreviewed') AS review_status,
                COALESCE(a.review_priority, 'normal') AS review_priority,
                COALESCE(a.stale_after_days, 14) AS stale_after_days
            FROM items i
            LEFT JOIN item_activity a
              ON a.item_key = i.type || '|' || i.language || '|' || i.normalized
            WHERE i.obsidian_path IS NOT NULL
              AND i.obsidian_path != ''
            ORDER BY i.type, i.language, i.text
            """
        ).fetchall()
    )


def row_to_updates(row: sqlite3.Row) -> dict[str, str]:
    return {
        "access_count": stringify_value(row["access_count"] or 0),
        "last_accessed_at": stringify_value(row["last_accessed_at"]),
        "last_reviewed_at": stringify_value(row["last_reviewed_at"]),
        "review_status": stringify_value(row["review_status"] or "unreviewed"),
        "review_priority": stringify_value(row["review_priority"] or "normal"),
        "stale_after_days": stringify_value(row["stale_after_days"] or 14),
    }


def frontmatter_needs_update(raw_frontmatter: str, updates: dict[str, str]) -> bool:
    for key, new_value in updates.items():
        pattern = rf"(?m)^\s*{re.escape(key)}\s*:\s*(.*)$"
        match = re.search(pattern, raw_frontmatter)

        if not match:
            return True

        old_value = match.group(1).strip()

        if old_value != new_value:
            return True

    return False


def sync_activity_to_notes(
    dry_run: bool,
    backup: bool,
    only_changed_with_activity: bool,
) -> dict:
    config = load_config()
    vault_root = Path(config["obsidian_vault"])
    db_path = get_db_path(config)
    backup_root = Path(config["languageos_root"]) / "Inbox" / "Backups" / "ActivitySync"

    conn = connect_db(db_path)
    rows = get_activity_rows(conn)
    conn.close()

    results: list[dict] = []

    totals = {
        "scanned": len(rows),
        "updated": 0,
        "unchanged": 0,
        "skipped": 0,
        "errors": 0,
    }

    for row in rows:
        try:
            access_count = int(row["access_count"] or 0)

            if only_changed_with_activity and access_count <= 0:
                totals["skipped"] += 1
                results.append(
                    {
                        "status": "skipped",
                        "reason": "access_count is 0",
                        "text": row["text"],
                        "path": row["obsidian_path"],
                    }
                )
                continue

            note_path = vault_root / str(row["obsidian_path"])

            if not note_path.exists():
                totals["skipped"] += 1
                results.append(
                    {
                        "status": "skipped",
                        "reason": "note file not found",
                        "text": row["text"],
                        "path": str(note_path),
                    }
                )
                continue

            text = note_path.read_text(encoding="utf-8")
            raw_frontmatter, body, has_frontmatter = split_frontmatter(text)

            if not has_frontmatter:
                totals["skipped"] += 1
                results.append(
                    {
                        "status": "skipped",
                        "reason": "missing frontmatter",
                        "text": row["text"],
                        "path": str(note_path),
                    }
                )
                continue

            updates = row_to_updates(row)

            if not frontmatter_needs_update(raw_frontmatter, updates):
                totals["unchanged"] += 1
                results.append(
                    {
                        "status": "unchanged",
                        "text": row["text"],
                        "path": str(note_path),
                    }
                )
                continue

            if not dry_run:
                if backup:
                    backup_file(note_path, backup_root)

                updated_frontmatter = update_frontmatter(raw_frontmatter, updates)
                new_text = f"---\n{updated_frontmatter}\n---\n\n{body}"
                note_path.write_text(new_text, encoding="utf-8")

            totals["updated"] += 1
            results.append(
                {
                    "status": "updated" if not dry_run else "would_update",
                    "text": row["text"],
                    "type": row["type"],
                    "language": row["language"],
                    "access_count": updates["access_count"],
                    "last_accessed_at": updates["last_accessed_at"],
                    "review_status": updates["review_status"],
                    "path": str(note_path),
                }
            )

        except Exception as exc:
            totals["errors"] += 1
            results.append(
                {
                    "status": "error",
                    "text": row["text"],
                    "path": row["obsidian_path"],
                    "reason": str(exc),
                }
            )

    return {
        "dry_run": dry_run,
        "backup": backup,
        "only_changed_with_activity": only_changed_with_activity,
        "db_path": str(db_path),
        "vault_root": str(vault_root),
        "totals": totals,
        "results": results,
    }


def print_summary(payload: dict) -> None:
    print("Sync Activity to Obsidian Notes")
    print("=" * 60)

    if payload["dry_run"]:
        print("[DRY RUN] No notes were changed.")

    print(f"DB         : {payload['db_path']}")
    print(f"Vault      : {payload['vault_root']}")
    print(f"Backup     : {payload['backup']}")
    print(f"Only active: {payload['only_changed_with_activity']}")

    print("\nSummary")
    print("-" * 60)

    totals = payload["totals"]

    print(f"[OK] Scanned items : {totals['scanned']}")
    print(f"[OK] Updated notes : {totals['updated']}")
    print(f"[OK] Unchanged     : {totals['unchanged']}")
    print(f"[SKIP] Skipped     : {totals['skipped']}")
    print(f"[ERROR] Errors     : {totals['errors']}")

    print("\nDetails")
    print("-" * 60)

    for result in payload["results"]:
        status = result["status"]
        text = result.get("text") or ""
        path = result.get("path") or ""

        if status == "would_update":
            print(
                f"[WOULD UPDATE] {text} | "
                f"access={result.get('access_count')} "
                f"review={result.get('review_status')} | {path}"
            )
        elif status == "updated":
            print(
                f"[UPDATE] {text} | "
                f"access={result.get('access_count')} "
                f"review={result.get('review_status')} | {path}"
            )
        elif status == "unchanged":
            print(f"[OK] {text} unchanged")
        elif status == "skipped":
            print(f"[SKIP] {text} — {result.get('reason')} | {path}")
        elif status == "error":
            print(f"[ERROR] {text} — {result.get('reason')} | {path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync LanguageOS activity fields from SQLite to Obsidian note properties.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing notes.",
    )

    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create backups before modifying notes.",
    )

    parser.add_argument(
        "--only-active",
        action="store_true",
        help="Only sync notes whose access_count is greater than 0.",
    )

    args = parser.parse_args()

    payload = sync_activity_to_notes(
        dry_run=args.dry_run,
        backup=not args.no_backup,
        only_changed_with_activity=args.only_active,
    )

    print_summary(payload)


if __name__ == "__main__":
    main()