from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

from languageos_tools.datastore.db import connect_db, get_or_create_lookup_id, init_db


CONFIG_PATH = Path("configs/languageos.config.json")


SCAN_FOLDERS = [
    "Vocabulary/English",
    "Vocabulary/German",
    "Sentences/English",
    "Sentences/German",
    "Grammar/English",
    "Grammar/German",
    "Listening/Transcripts",
    "Speaking/TTS",
    "Writing",
]


AGGREGATE_NOTE_NAMES = {
    "Vocabulary Inbox.md",
    "Sentence Bank.md",
    "Writing Error Log.md",
    "Writing Practice.md",
}


TYPE_ALIASES = {
    "listening_transcript": "transcript",
    "transcript": "transcript",
    "tts_audio": "tts_audio",
    "vocabulary": "vocabulary",
    "sentence": "sentence",
    "grammar": "grammar",
    "writing_error": "writing_error",
}


LANGUAGE_ALIASES = {
    "en": "english",
    "eng": "english",
    "english": "english",
    "de": "german",
    "deu": "german",
    "ger": "german",
    "german": "german",
    "mixed": "mixed",
    "unknown": "unknown",
    "auto": "unknown",
}


TYPE_TEXT_FIELD = {
    "vocabulary": "term",
    "sentence": "sentence",
    "grammar": "title",
    "transcript": "source_file",
    "tts_audio": "audio_file",
    "writing_error": "title",
}


DEFAULT_STATUS_BY_TYPE = {
    "vocabulary": "learning",
    "sentence": "learning",
    "grammar": "learning",
    "transcript": "raw_transcript",
    "tts_audio": "generated",
    "writing_error": "learning",
}


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalize_text(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[“”\"'`]", "", text)

    # Do not let final sentence punctuation create duplicate items.
    # Example:
    # "Guten Morgen"
    # "Guten Morgen."
    # should share the same normalized key.
    text = re.sub(r"[.!?。！？]+$", "", text)

    text = text.strip()
    return text


def parse_scalar_value(value: str) -> str:
    value = value.strip()

    if value in {"", "null", "None"}:
        return ""

    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]

    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]

    return value


def parse_frontmatter(text: str) -> tuple[dict, str, bool]:
    if not text.startswith("---"):
        return {}, text, False

    parts = text.split("---", 2)

    if len(parts) < 3:
        return {}, text, False

    frontmatter_text = parts[1]
    body = parts[2].lstrip("\n")

    metadata: dict = {}
    current_list_key: str | None = None

    for raw_line in frontmatter_text.splitlines():
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

    return metadata, body, True


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


def infer_type_from_path(path: Path) -> str:
    path_text = path.as_posix().lower()

    if "/vocabulary/" in path_text:
        return "vocabulary"

    if "/sentences/" in path_text:
        return "sentence"

    if "/grammar/" in path_text:
        return "grammar"

    if "/listening/transcripts/" in path_text:
        return "transcript"

    if "/speaking/tts/" in path_text:
        return "tts_audio"

    if "/writing/" in path_text:
        return "writing_error"

    return "unknown"


def infer_language_from_path(path: Path) -> str:
    path_text = path.as_posix().lower()

    if "/german/" in path_text:
        return "german"

    if "/english/" in path_text:
        return "english"

    return "unknown"


def normalize_item_type(raw_type: str | None, path: Path) -> str:
    if raw_type:
        raw_type_normalized = raw_type.strip().lower()

        if raw_type_normalized in TYPE_ALIASES:
            return TYPE_ALIASES[raw_type_normalized]

    inferred_type = infer_type_from_path(path)

    if inferred_type in TYPE_ALIASES:
        return TYPE_ALIASES[inferred_type]

    return inferred_type


def normalize_language_value(value: str | None) -> str:
    if not value:
        return "unknown"

    normalized = value.strip().lower()

    return LANGUAGE_ALIASES.get(normalized, normalized)


def normalize_language(metadata: dict, path: Path) -> str:
    direct_language = normalize_language_value(str(metadata.get("language") or ""))

    if direct_language != "unknown":
        return direct_language

    language_setting = normalize_language_value(str(metadata.get("language_setting") or ""))

    if language_setting != "unknown":
        return language_setting

    detected_language = normalize_language_value(str(metadata.get("detected_language") or ""))

    if detected_language != "unknown":
        return detected_language

    return infer_language_from_path(path)


def normalize_status(metadata: dict, item_type: str) -> str:
    status = str(metadata.get("status") or "").strip().lower()

    if status:
        return status

    return DEFAULT_STATUS_BY_TYPE.get(item_type, "unknown")


def normalize_anki_status(metadata: dict) -> str:
    anki_status = str(metadata.get("anki_status") or "").strip().lower()

    if anki_status:
        return anki_status

    return "none"


def infer_title_from_body_or_path(path: Path, body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()

        if stripped.startswith("# "):
            return stripped.replace("#", "", 1).strip()

    return path.stem


def resolve_item_text(path: Path, metadata: dict, body: str, item_type: str) -> str:
    field_name = TYPE_TEXT_FIELD.get(item_type)

    if field_name:
        value = metadata.get(field_name)

        if isinstance(value, str) and value.strip():
            return value.strip()

    if item_type == "vocabulary" and metadata.get("term"):
        return str(metadata["term"]).strip()

    if item_type == "sentence" and metadata.get("sentence"):
        return str(metadata["sentence"]).strip()

    if item_type == "transcript":
        value = metadata.get("source_file") or metadata.get("source_path")

        if isinstance(value, str) and value.strip():
            return Path(value).name

    if item_type == "tts_audio":
        value = metadata.get("audio_file") or metadata.get("audio_path")

        if isinstance(value, str) and value.strip():
            return Path(value).name

    return infer_title_from_body_or_path(path, body)


def safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def build_obsidian_link(relative_path: str, alias: str) -> str:
    note_path = relative_path

    if note_path.endswith(".md"):
        note_path = note_path[:-3]

    return f"[[{note_path}|{alias}]]"


def should_skip_note(path: Path, has_frontmatter: bool) -> bool:
    if path.name in AGGREGATE_NOTE_NAMES:
        return True

    if not has_frontmatter:
        return True

    return False


def scan_markdown_files(vault_root: Path) -> list[Path]:
    markdown_files: list[Path] = []

    for folder in SCAN_FOLDERS:
        folder_path = vault_root / folder

        if not folder_path.exists():
            continue

        markdown_files.extend(folder_path.rglob("*.md"))

    return sorted(set(markdown_files))


def default_topic_for_type(item_type: str) -> list[str]:
    if item_type == "transcript":
        return ["listening"]

    if item_type == "tts_audio":
        return ["speaking"]

    if item_type == "vocabulary":
        return ["vocabulary"]

    if item_type == "sentence":
        return ["daily_life"]

    if item_type == "grammar":
        return ["grammar"]

    if item_type == "writing_error":
        return ["writing_errors"]

    return []


def default_skill_for_type(item_type: str) -> list[str]:
    if item_type == "transcript":
        return ["listening"]

    if item_type == "tts_audio":
        return ["speaking", "listening"]

    if item_type == "vocabulary":
        return ["vocabulary"]

    if item_type == "sentence":
        return ["speaking", "listening"]

    if item_type == "grammar":
        return ["grammar"]

    if item_type == "writing_error":
        return ["writing"]

    return []


def default_source_type_for_type(item_type: str) -> str:
    if item_type == "transcript":
        return "stt"

    if item_type == "tts_audio":
        return "tts"

    if item_type == "writing_error":
        return "writing"

    return "manual"


def clean_body_for_search(body: str) -> str:
    """
    Keep note content searchable, but remove some markdown noise.
    """
    text = body

    # Obsidian wikilinks:
    # [[Path/Note|alias]] -> alias
    # [[Path/Note]] -> Path/Note
    text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)

    # Markdown links:
    # [text](url) -> text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    # Collapse whitespace.
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def build_item_from_note(
    vault_root: Path,
    path: Path,
    metadata: dict,
    body: str,
) -> dict:
    item_type = normalize_item_type(
        raw_type=str(metadata.get("type") or ""),
        path=path,
    )

    language = normalize_language(
        metadata=metadata,
        path=path,
    )

    text = resolve_item_text(
        path=path,
        metadata=metadata,
        body=body,
        item_type=item_type,
    )

    # Always recompute normalized text for the database.
    # Frontmatter may contain old normalized values from earlier versions.
    normalized = normalize_text(text)
    relative_path = path.relative_to(vault_root).as_posix()

    status = normalize_status(
        metadata=metadata,
        item_type=item_type,
    )

    anki_status = normalize_anki_status(metadata)

    topic = ensure_list(metadata.get("topic"))

    if not topic:
        topic = default_topic_for_type(item_type)

    skill = ensure_list(metadata.get("skill"))

    if not skill:
        skill = default_skill_for_type(item_type)

    source_type = str(metadata.get("source_type") or "").strip().lower()

    if not source_type:
        source_type = default_source_type_for_type(item_type)

    return {
        "type": item_type,
        "language": language,
        "text": text,
        "normalized": normalized,
        "status": status,
        "anki_status": anki_status,
        "anki_note_id": str(metadata.get("anki_note_id") or ""),
        "topic": topic,
        "level": str(metadata.get("level") or "unknown"),
        "skill": skill,
        "source_type": source_type,
        "source": str(metadata.get("source") or metadata.get("source_file") or ""),
        "seen_count": safe_int(metadata.get("seen_count"), default=0),
        "first_seen": str(metadata.get("first_seen") or ""),
        "last_seen": str(metadata.get("last_seen") or ""),
        "difficulty": str(metadata.get("difficulty") or "unknown"),
        "confidence": str(metadata.get("confidence") or "unknown"),
        "obsidian_path": relative_path,
        "obsidian_link": build_obsidian_link(relative_path, text),
        "created_at": str(metadata.get("created_at") or ""),
        "updated_at": str(metadata.get("updated_at") or ""),
    }


def clear_database(conn: sqlite3.Connection) -> None:
    tables = [
        "search_documents_fts",
        "embeddings",
        "relations",
        "contexts",
        "aliases",
        "item_topics",
        "item_skills",
        "items",
        "sources",
        "topics",
        "skills",
    ]

    for table in tables:
        conn.execute(f"DELETE FROM {table}")

    conn.commit()


def upsert_item(conn: sqlite3.Connection, item: dict) -> int:
    now = datetime.now().isoformat(timespec="seconds")

    created_at = item["created_at"] or now
    updated_at = item["updated_at"] or now

    conn.execute(
        """
        INSERT INTO items (
            type,
            language,
            text,
            normalized,
            status,
            anki_status,
            anki_note_id,
            level,
            source_type,
            source,
            seen_count,
            first_seen,
            last_seen,
            difficulty,
            confidence,
            obsidian_path,
            obsidian_link,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(type, language, normalized)
        DO UPDATE SET
            text = excluded.text,
            status = excluded.status,
            anki_status = excluded.anki_status,
            anki_note_id = excluded.anki_note_id,
            level = excluded.level,
            source_type = excluded.source_type,
            source = excluded.source,
            seen_count = excluded.seen_count,
            first_seen = excluded.first_seen,
            last_seen = excluded.last_seen,
            difficulty = excluded.difficulty,
            confidence = excluded.confidence,
            obsidian_path = excluded.obsidian_path,
            obsidian_link = excluded.obsidian_link,
            updated_at = excluded.updated_at
        """,
        (
            item["type"],
            item["language"],
            item["text"],
            item["normalized"],
            item["status"],
            item["anki_status"],
            item["anki_note_id"],
            item["level"],
            item["source_type"],
            item["source"],
            item["seen_count"],
            item["first_seen"],
            item["last_seen"],
            item["difficulty"],
            item["confidence"],
            item["obsidian_path"],
            item["obsidian_link"],
            created_at,
            updated_at,
        ),
    )

    row = conn.execute(
        """
        SELECT id FROM items
        WHERE type = ? AND language = ? AND normalized = ?
        """,
        (
            item["type"],
            item["language"],
            item["normalized"],
        ),
    ).fetchone()

    if row is None:
        raise RuntimeError(f"Failed to upsert item: {item['text']}")

    item_id = int(row["id"])

    sync_topics(conn, item_id, item["topic"])
    sync_skills(conn, item_id, item["skill"])

    return item_id


def sync_topics(conn: sqlite3.Connection, item_id: int, topics: list[str]) -> None:
    conn.execute(
        "DELETE FROM item_topics WHERE item_id = ?",
        (item_id,),
    )

    for topic in topics:
        topic_id = get_or_create_lookup_id(conn, "topics", topic)

        conn.execute(
            "INSERT OR IGNORE INTO item_topics (item_id, topic_id) VALUES (?, ?)",
            (item_id, topic_id),
        )


def sync_skills(conn: sqlite3.Connection, item_id: int, skills: list[str]) -> None:
    conn.execute(
        "DELETE FROM item_skills WHERE item_id = ?",
        (item_id,),
    )

    for skill in skills:
        skill_id = get_or_create_lookup_id(conn, "skills", skill)

        conn.execute(
            "INSERT OR IGNORE INTO item_skills (item_id, skill_id) VALUES (?, ?)",
            (item_id, skill_id),
        )


def insert_search_document(
    conn: sqlite3.Connection,
    item_id: int,
    item: dict,
    body: str,
) -> None:
    """
    Index full note body into SQLite FTS5.

    This is what makes queries like "Guten Morgen" find matches
    inside transcript notes, not only item names.
    """
    title = str(item.get("text") or "")
    body_for_search = clean_body_for_search(body)

    conn.execute(
        """
        INSERT INTO search_documents_fts (
            item_id,
            doc_type,
            language,
            status,
            title,
            body,
            path,
            obsidian_link
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(item_id),
            item["type"],
            item["language"],
            item["status"],
            title,
            body_for_search,
            item["obsidian_path"],
            item["obsidian_link"],
        ),
    )


def rebuild_database(config: dict) -> dict:
    vault_root = Path(config["obsidian_vault"])
    db_path = Path(config["outputs"]["languageos_db"])

    if not vault_root.exists():
        raise FileNotFoundError(f"Obsidian vault not found: {vault_root}")

    conn = connect_db(db_path)
    init_db(conn)
    clear_database(conn)

    markdown_files = scan_markdown_files(vault_root)

    indexed_items: list[dict] = []
    skipped_files: list[str] = []
    errors: list[dict] = []

    for path in markdown_files:
        try:
            text = path.read_text(encoding="utf-8")
            metadata, body, has_frontmatter = parse_frontmatter(text)

            if should_skip_note(path, has_frontmatter):
                skipped_files.append(str(path))
                continue

            item_type = normalize_item_type(
                raw_type=str(metadata.get("type") or ""),
                path=path,
            )

            if item_type == "unknown":
                skipped_files.append(str(path))
                continue

            item = build_item_from_note(
                vault_root=vault_root,
                path=path,
                metadata=metadata,
                body=body,
            )

            if not item["text"]:
                skipped_files.append(str(path))
                continue

            item_id = upsert_item(conn, item)
            insert_search_document(conn, item_id, item, body)

            item["id"] = item_id
            indexed_items.append(item)

        except Exception as exc:
            errors.append(
                {
                    "path": str(path),
                    "error": str(exc),
                }
            )

    conn.commit()

    type_counts = Counter(item["type"] for item in indexed_items)
    language_counts = Counter(item["language"] for item in indexed_items)
    status_counts = Counter(item["status"] for item in indexed_items)
    anki_status_counts = Counter(item["anki_status"] for item in indexed_items)

    payload = {
        "db_path": str(db_path),
        "indexed_count": len(indexed_items),
        "fts_documents": len(indexed_items),
        "skipped_count": len(skipped_files),
        "error_count": len(errors),
        "summary": {
            "by_type": dict(type_counts),
            "by_language": dict(language_counts),
            "by_status": dict(status_counts),
            "by_anki_status": dict(anki_status_counts),
        },
        "skipped_files": skipped_files,
        "errors": errors,
    }

    conn.close()

    return payload


def print_summary(payload: dict) -> None:
    print("\nSummary")
    print("-" * 60)
    print(f"[OK] DB path: {payload['db_path']}")
    print(f"[OK] Indexed items: {payload['indexed_count']}")
    print(f"[OK] FTS documents: {payload['fts_documents']}")
    print(f"[SKIP] Skipped files: {payload['skipped_count']}")
    print(f"[ERROR] Errors: {payload['error_count']}")

    print("\nBy type:")
    for key, value in payload["summary"]["by_type"].items():
        print(f"- {key}: {value}")

    print("\nBy language:")
    for key, value in payload["summary"]["by_language"].items():
        print(f"- {key}: {value}")

    print("\nBy status:")
    for key, value in payload["summary"]["by_status"].items():
        print(f"- {key}: {value}")

    print("\nBy Anki status:")
    for key, value in payload["summary"]["by_anki_status"].items():
        print(f"- {key}: {value}")

    if payload["errors"]:
        print("\nErrors:")
        for error in payload["errors"]:
            print(f"- {error['path']}: {error['error']}")


def main() -> None:
    print("Build LanguageOS SQLite Database")
    print("=" * 60)

    config = load_config()
    payload = rebuild_database(config)
    print_summary(payload)


if __name__ == "__main__":
    main()