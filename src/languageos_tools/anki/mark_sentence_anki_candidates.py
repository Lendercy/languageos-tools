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


def parse_scalar_value(value: str) -> str:
    value = value.strip()

    if value in {"", "null", "None"}:
        return ""

    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]

    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]

    return value


def parse_frontmatter(text: str) -> tuple[dict, str, str, bool]:
    """
    Returns:
    metadata, raw_frontmatter, body, has_frontmatter

    raw_frontmatter is kept so we can update only selected fields
    without rewriting/corrupting the whole YAML block.
    """
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


def get_markdown_section(body: str, heading: str) -> str:
    pattern = rf"(?ims)^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)"
    match = re.search(pattern, body)

    if not match:
        return ""

    return match.group(1).strip()


def clean_section_text(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def is_meaning_ready(meaning: str) -> bool:
    value = meaning.strip()

    if not value:
        return False

    bad_values = {
        "todo",
        "TODO",
        "Todo",
        "-",
        "...",
        "tbd",
        "TBD",
        "none",
        "None",
    }

    if value in bad_values:
        return False

    return True


def safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def update_frontmatter(raw_frontmatter: str, updates: dict[str, str]) -> str:
    lines = raw_frontmatter.splitlines()
    remaining = dict(updates)
    output_lines: list[str] = []

    for line in lines:
        match = re.match(r"^(\s*)([A-Za-z0-9_]+)(\s*:\s*)(.*)$", line)

        if not match:
            output_lines.append(line)
            continue

        indent, key, sep, _value = match.groups()

        if key in remaining:
            output_lines.append(f"{indent}{key}{sep}{remaining.pop(key)}")
        else:
            output_lines.append(line)

    for key, value in remaining.items():
        output_lines.append(f"{key}: {value}")

    return "\n".join(output_lines)


def write_updated_note(
    note_path: Path,
    raw_frontmatter: str,
    body: str,
    updates: dict[str, str],
) -> None:
    updated_frontmatter = update_frontmatter(raw_frontmatter, updates)
    new_text = f"---\n{updated_frontmatter}\n---\n\n{body}"
    note_path.write_text(new_text, encoding="utf-8")


def find_sentence_notes(vault_root: Path) -> list[Path]:
    sentence_root = vault_root / "Sentences"

    if not sentence_root.exists():
        return []

    return sorted(sentence_root.rglob("*.md"))


def should_mark_candidate(
    metadata: dict,
    body: str,
    min_seen: int,
    all_ready: bool,
) -> tuple[bool, str]:
    note_type = str(metadata.get("type") or "").strip().lower()

    if note_type != "sentence":
        return False, f"not sentence type: {note_type}"

    anki_status = str(metadata.get("anki_status") or "none").strip().lower()

    if anki_status not in {"none", ""}:
        return False, f"anki_status already {anki_status}"

    sentence_status = str(metadata.get("status") or "").strip().lower()

    if sentence_status in {"ignored", "archived"}:
        return False, f"sentence status is {sentence_status}"

    meaning = clean_section_text(get_markdown_section(body, "Meaning"))

    if not is_meaning_ready(meaning):
        return False, "meaning is empty or TODO"

    seen_count = safe_int(metadata.get("seen_count"), default=0)

    if all_ready:
        return True, "ready meaning and --all-ready enabled"

    if seen_count < min_seen:
        return False, f"seen_count {seen_count} < min_seen {min_seen}"

    return True, f"seen_count {seen_count} >= min_seen {min_seen}"


def mark_sentence_candidates(
    min_seen: int,
    all_ready: bool,
    dry_run: bool,
) -> dict:
    config = load_config()
    vault_root = Path(config["obsidian_vault"])

    sentence_notes = find_sentence_notes(vault_root)

    results: list[dict] = []

    totals = {
        "scanned": len(sentence_notes),
        "marked": 0,
        "ready_dry_run": 0,
        "skipped": 0,
        "errors": 0,
    }

    for note_path in sentence_notes:
        try:
            text = note_path.read_text(encoding="utf-8")
            metadata, raw_frontmatter, body, has_frontmatter = parse_frontmatter(text)

            if not has_frontmatter:
                totals["skipped"] += 1
                results.append(
                    {
                        "path": str(note_path),
                        "status": "skipped",
                        "reason": "missing frontmatter",
                    }
                )
                continue

            should_mark, reason = should_mark_candidate(
                metadata=metadata,
                body=body,
                min_seen=min_seen,
                all_ready=all_ready,
            )

            sentence = str(metadata.get("sentence") or note_path.stem)

            if not should_mark:
                totals["skipped"] += 1
                results.append(
                    {
                        "path": str(note_path),
                        "status": "skipped",
                        "sentence": sentence,
                        "reason": reason,
                    }
                )
                continue

            if dry_run:
                totals["ready_dry_run"] += 1
                results.append(
                    {
                        "path": str(note_path),
                        "status": "ready",
                        "sentence": sentence,
                        "reason": reason,
                    }
                )
                continue

            now = datetime.now().isoformat(timespec="seconds")

            write_updated_note(
                note_path=note_path,
                raw_frontmatter=raw_frontmatter,
                body=body,
                updates={
                    "anki_status": "candidate",
                    "updated_at": now,
                },
            )

            totals["marked"] += 1
            results.append(
                {
                    "path": str(note_path),
                    "status": "marked",
                    "sentence": sentence,
                    "reason": reason,
                }
            )

        except Exception as exc:
            totals["errors"] += 1
            results.append(
                {
                    "path": str(note_path),
                    "status": "error",
                    "reason": str(exc),
                }
            )

    return {
        "dry_run": dry_run,
        "min_seen": min_seen,
        "all_ready": all_ready,
        "totals": totals,
        "results": results,
    }


def print_summary(payload: dict) -> None:
    print("Mark Sentence Anki Candidates")
    print("=" * 60)

    if payload["dry_run"]:
        print("[DRY RUN] No notes were changed.")

    print("\nRules")
    print("-" * 60)
    print(f"min_seen  : {payload['min_seen']}")
    print(f"all_ready : {payload['all_ready']}")

    print("\nSummary")
    print("-" * 60)

    totals = payload["totals"]

    print(f"[OK] Scanned sentence notes : {totals['scanned']}")
    print(f"[OK] Ready in dry-run      : {totals['ready_dry_run']}")
    print(f"[OK] Marked as candidate   : {totals['marked']}")
    print(f"[SKIP] Skipped             : {totals['skipped']}")
    print(f"[ERROR] Errors             : {totals['errors']}")

    print("\nDetails")
    print("-" * 60)

    for result in payload["results"]:
        status = result["status"]
        sentence = result.get("sentence") or result["path"]
        reason = result.get("reason") or ""

        if status == "ready":
            print(f"[READY] {sentence} — {reason}")
        elif status == "marked":
            print(f"[MARK] {sentence} — {reason}")
        elif status == "skipped":
            print(f"[SKIP] {sentence} — {reason}")
        elif status == "error":
            print(f"[ERROR] {result['path']} — {reason}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mark selected sentence notes as Anki candidates.",
    )

    parser.add_argument(
        "--min-seen",
        type=int,
        default=2,
        help="Minimum seen_count required before marking as candidate.",
    )

    parser.add_argument(
        "--all-ready",
        action="store_true",
        help="Mark all sentence notes that have a ready Meaning, ignoring seen_count.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without modifying notes.",
    )

    args = parser.parse_args()

    payload = mark_sentence_candidates(
        min_seen=args.min_seen,
        all_ready=args.all_ready,
        dry_run=args.dry_run,
    )

    print_summary(payload)


if __name__ == "__main__":
    main()
