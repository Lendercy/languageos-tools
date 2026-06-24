from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path


CONFIG_PATH = Path("configs/languageos.config.json")


LANGUAGE_ALIASES = {
    "en": "english",
    "eng": "english",
    "english": "english",
    "de": "german",
    "deu": "german",
    "ger": "german",
    "german": "german",
}


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def connect_db(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(
            f"LanguageOS database not found: {db_path}\n"
            "Run: python scripts\\build_language_db.py"
        )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def normalize_text(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[“”\"'`]", "", text)
    text = re.sub(r"[.!?。！？]+$", "", text)
    text = text.strip()
    return text


def normalize_language(value: str | None) -> str:
    if not value:
        return "unknown"

    value = value.strip().lower()
    return LANGUAGE_ALIASES.get(value, value)


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

    Important:
    raw_frontmatter is preserved exactly so this script does not corrupt
    Windows paths like D:/Dev/... or D:\\Dev\\...
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


def infer_language_from_metadata(metadata: dict) -> str:
    for key in ["language", "language_setting", "detected_language"]:
        language = normalize_language(str(metadata.get(key) or ""))

        if language != "unknown":
            return language

    return "unknown"


def get_markdown_section(body: str, heading: str) -> str:
    pattern = rf"(?ims)^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)"
    match = re.search(pattern, body)

    if not match:
        return ""

    return match.group(1).strip()


def remove_existing_annotated_section(body: str) -> str:
    pattern = r"(?ims)^##\s+Annotated Transcript\s*$\n.*?(?=^##\s+|\Z)"
    return re.sub(pattern, "", body).rstrip()


def clean_transcript_text(text: str) -> str:
    text = re.sub(
        r"`?\[\d{2}:\d{2}:\d{2}\s*-\s*\d{2}:\d{2}:\d{2}\]`?",
        " ",
        text,
    )
    text = re.sub(
        r"`?\[\d{2}:\d{2}\s*-\s*\d{2}:\d{2}\]`?",
        " ",
        text,
    )

    text = re.sub(r"^#+\s+.*$", " ", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*]\s+", " ", text, flags=re.MULTILINE)

    text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    text = text.replace("\r", " ")
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def extract_transcript_text(body: str) -> str:
    raw_transcript = get_markdown_section(body, "Raw Transcript")

    if raw_transcript:
        return clean_transcript_text(raw_transcript)

    full_transcript = get_markdown_section(body, "Full Transcript")

    if full_transcript:
        return clean_transcript_text(full_transcript)

    timestamped = get_markdown_section(body, "Timestamped Transcript")

    if timestamped:
        return clean_transcript_text(timestamped)

    return clean_transcript_text(body)


def split_sentences(text: str) -> list[str]:
    text = text.strip()

    if not text:
        return []

    parts = re.split(r"(?<=[.!?。！？])\s+", text)

    sentences: list[str] = []

    for part in parts:
        sentence = part.strip()

        if not sentence:
            continue

        if len(sentence) < 2:
            continue

        if len(sentence) > 300:
            continue

        sentences.append(sentence)

    return dedupe_keep_order(sentences)


def dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []

    for value in values:
        key = normalize_text(value)

        if key in seen:
            continue

        seen.add(key)
        result.append(value)

    return result


def find_sentence_item(
    conn: sqlite3.Connection,
    sentence: str,
    language: str,
) -> dict | None:
    normalized = normalize_text(sentence)

    row = conn.execute(
        """
        SELECT *
        FROM items
        WHERE type = 'sentence'
          AND language = ?
          AND normalized = ?
        LIMIT 1
        """,
        (language, normalized),
    ).fetchone()

    if row:
        return dict(row)

    return None


def status_to_icon(status: str) -> str:
    status = status.strip().lower()

    if status == "new":
        return "🔴"

    if status == "learning":
        return "🟡"

    if status == "learned":
        return "✅"

    if status == "generated":
        return "🔊"

    if status == "raw_transcript":
        return "🎧"

    return "❔"


def html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_obsidian_link_from_item(item: dict, display_text: str) -> str:
    path = str(item.get("obsidian_path") or "")

    if path.endswith(".md"):
        path = path[:-3]

    if not path:
        return html_escape(display_text)

    return f"[[{path}|{display_text}]]"


def build_annotated_sentence(sentence: str, item: dict | None) -> str:
    if item is None:
        return f'<span class="los-new">● {html_escape(sentence)}</span>'

    status = str(item.get("status") or "unknown")
    anki_status = str(item.get("anki_status") or "none")

    icon = status_to_icon(status)

    if anki_status in {"added", "duplicate"}:
        icon = f"{icon} 📌"

    obsidian_link = build_obsidian_link_from_item(item, sentence)

    return f"{icon} {obsidian_link}"


def annotate_transcript_note(
    transcript_path: Path,
    conn: sqlite3.Connection,
    dry_run: bool,
) -> dict:
    text = transcript_path.read_text(encoding="utf-8")
    metadata, raw_frontmatter, body, has_frontmatter = parse_frontmatter(text)

    if not has_frontmatter:
        return {
            "path": str(transcript_path),
            "status": "skipped",
            "reason": "missing frontmatter",
        }

    note_type = str(metadata.get("type") or "").strip().lower()

    if note_type not in {"transcript", "listening_transcript"}:
        return {
            "path": str(transcript_path),
            "status": "skipped",
            "reason": f"not transcript type: {note_type}",
        }

    language = infer_language_from_metadata(metadata)

    if language == "unknown":
        return {
            "path": str(transcript_path),
            "status": "skipped",
            "reason": "unknown language",
        }

    transcript_text = extract_transcript_text(body)
    sentences = split_sentences(transcript_text)

    annotated_sentences: list[str] = []
    found_count = 0
    new_count = 0

    for sentence in sentences:
        item = find_sentence_item(
            conn=conn,
            sentence=sentence,
            language=language,
        )

        if item:
            found_count += 1
        else:
            new_count += 1

        annotated_sentences.append(build_annotated_sentence(sentence, item))

    annotated_block = (
        "\n\n## Annotated Transcript\n\n"
        + "\n\n".join(annotated_sentences)
        + "\n"
    )

    body_without_old_annotation = remove_existing_annotated_section(body)
    new_text = f"---\n{raw_frontmatter}\n---\n\n{body_without_old_annotation.rstrip()}{annotated_block}"

    if not dry_run:
        transcript_path.write_text(new_text, encoding="utf-8")

    return {
        "path": str(transcript_path),
        "status": "processed",
        "language": language,
        "sentences": len(sentences),
        "found": found_count,
        "new": new_count,
    }


def find_transcript_notes(vault_root: Path) -> list[Path]:
    transcript_dir = vault_root / "Listening" / "Transcripts"

    if not transcript_dir.exists():
        return []

    return sorted(transcript_dir.rglob("*.md"))


def annotate_all_transcripts(dry_run: bool = False) -> dict:
    config = load_config()
    vault_root = Path(config["obsidian_vault"])
    db_path = Path(config["outputs"]["languageos_db"])

    if not vault_root.exists():
        raise FileNotFoundError(f"Obsidian vault not found: {vault_root}")

    conn = connect_db(db_path)
    transcript_notes = find_transcript_notes(vault_root)

    results: list[dict] = []
    totals = {
        "processed": 0,
        "skipped": 0,
        "sentences": 0,
        "found": 0,
        "new": 0,
    }

    for transcript_path in transcript_notes:
        result = annotate_transcript_note(
            transcript_path=transcript_path,
            conn=conn,
            dry_run=dry_run,
        )

        results.append(result)

        if result["status"] == "processed":
            totals["processed"] += 1
            totals["sentences"] += int(result.get("sentences", 0))
            totals["found"] += int(result.get("found", 0))
            totals["new"] += int(result.get("new", 0))
        else:
            totals["skipped"] += 1

    conn.close()

    return {
        "dry_run": dry_run,
        "transcript_notes": len(transcript_notes),
        "totals": totals,
        "results": results,
    }


def print_summary(payload: dict) -> None:
    print("Annotate Transcript Notes")
    print("=" * 60)

    if payload["dry_run"]:
        print("[DRY RUN] No files were written.")

    print("\nSummary")
    print("-" * 60)
    print(f"[OK] Transcript notes found : {payload['transcript_notes']}")
    print(f"[OK] Processed transcript  : {payload['totals']['processed']}")
    print(f"[SKIP] Skipped transcript  : {payload['totals']['skipped']}")
    print(f"[OK] Sentences checked     : {payload['totals']['sentences']}")
    print(f"[OK] Known sentence matches: {payload['totals']['found']}")
    print(f"[OK] New sentence segments : {payload['totals']['new']}")

    print("\nDetails")
    print("-" * 60)

    for result in payload["results"]:
        if result["status"] != "processed":
            print(f"[SKIP] {result['path']} — {result.get('reason')}")
            continue

        print(
            f"[OK] {result['path']} | "
            f"sentences={result.get('sentences', 0)} "
            f"found={result.get('found', 0)} "
            f"new={result.get('new', 0)}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Annotate transcript notes using sentence status from the LanguageOS database.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview annotation without writing transcript notes.",
    )

    args = parser.parse_args()

    payload = annotate_all_transcripts(dry_run=args.dry_run)
    print_summary(payload)


if __name__ == "__main__":
    main()