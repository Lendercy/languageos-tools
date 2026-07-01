from __future__ import annotations

import argparse
import json
import re
import sqlite3
from difflib import SequenceMatcher
from pathlib import Path

CONFIG_PATH = Path("configs/languageos.config.json")


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalize_text(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[“”\"'`]", "", text)

    # Sentence lookup should not fail only because of ending punctuation.
    # Example:
    # "Ich lerne jeden Tag Deutsch"
    # "Ich lerne jeden Tag Deutsch."
    # should be considered the same normalized sentence.
    text = re.sub(r"[.!?。！？]+$", "", text)

    text = text.strip()
    return text


def connect_db(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(
            f"LanguageOS database not found: {db_path}\n"
            "Run: python scripts\\build_language_db.py"
        )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def get_item_topics(conn: sqlite3.Connection, item_id: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT topics.name
        FROM item_topics
        JOIN topics ON topics.id = item_topics.topic_id
        WHERE item_topics.item_id = ?
        ORDER BY topics.name
        """,
        (item_id,),
    ).fetchall()

    return [str(row["name"]) for row in rows]


def get_item_skills(conn: sqlite3.Connection, item_id: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT skills.name
        FROM item_skills
        JOIN skills ON skills.id = item_skills.skill_id
        WHERE item_skills.item_id = ?
        ORDER BY skills.name
        """,
        (item_id,),
    ).fetchall()

    return [str(row["name"]) for row in rows]


def enrich_item(conn: sqlite3.Connection, item: dict) -> dict:
    item_id = int(item["id"])
    item["topic"] = get_item_topics(conn, item_id)
    item["skill"] = get_item_skills(conn, item_id)
    return item


def exact_lookup(
    conn: sqlite3.Connection,
    query_normalized: str,
    language: str | None,
    item_type: str | None,
) -> list[dict]:
    sql = """
        SELECT *
        FROM items
        WHERE normalized = ?
    """

    params: list[object] = [query_normalized]

    if language:
        sql += " AND language = ?"
        params.append(language)

    if item_type:
        sql += " AND type = ?"
        params.append(item_type)

    sql += " ORDER BY seen_count DESC, updated_at DESC"

    rows = conn.execute(sql, params).fetchall()
    return [enrich_item(conn, row_to_dict(row)) for row in rows]


def similarity_score(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio() * 100.0


def fetch_candidate_items(
    conn: sqlite3.Connection,
    language: str | None,
    item_type: str | None,
) -> list[dict]:
    sql = "SELECT * FROM items"
    conditions: list[str] = []
    params: list[object] = []

    if language:
        conditions.append("language = ?")
        params.append(language)

    if item_type:
        conditions.append("type = ?")
        params.append(item_type)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    rows = conn.execute(sql, params).fetchall()
    return [row_to_dict(row) for row in rows]


def fuzzy_lookup(
    conn: sqlite3.Connection,
    query_normalized: str,
    language: str | None,
    item_type: str | None,
    threshold: float,
    limit: int,
) -> list[dict]:
    candidates = fetch_candidate_items(
        conn=conn,
        language=language,
        item_type=item_type,
    )

    scored: list[dict] = []

    for item in candidates:
        item_normalized = str(item.get("normalized") or "")

        if not item_normalized:
            continue

        score = similarity_score(query_normalized, item_normalized)

        if score >= threshold:
            enriched = enrich_item(conn, item)
            enriched["match_score"] = round(score, 2)
            scored.append(enriched)

    scored.sort(
        key=lambda item: (
            item.get("match_score", 0),
            item.get("seen_count", 0),
        ),
        reverse=True,
    )

    return scored[:limit]


def status_icon(status: str) -> str:
    status = status.strip().lower()

    if status == "learned":
        return "✅"

    if status == "learning":
        return "🟡"

    if status == "new":
        return "🟠"

    if status == "generated":
        return "🔊"

    if status == "raw_transcript":
        return "🎧"

    if status == "ignored":
        return "⚪"

    return "❔"


def anki_icon(anki_status: str) -> str:
    anki_status = anki_status.strip().lower()

    if anki_status == "added":
        return "📌"

    if anki_status == "candidate":
        return "📝"

    if anki_status == "duplicate":
        return "📌"

    if anki_status == "error":
        return "❌"

    return "—"


def print_item(item: dict, index: int, label: str) -> None:
    status = str(item.get("status") or "unknown")
    anki_status = str(item.get("anki_status") or "none")

    print(f"\n[{label} #{index}] {item.get('text')}")
    print("-" * 60)

    if "match_score" in item:
        print(f"Match score : {item['match_score']}")

    print(f"Type        : {item.get('type')}")
    print(f"Language    : {item.get('language')}")
    print(f"Status      : {status_icon(status)} {status}")
    print(f"Anki        : {anki_icon(anki_status)} {anki_status}")
    print(f"Level       : {item.get('level')}")
    print(f"Seen count  : {item.get('seen_count')}")
    print(f"Topics      : {', '.join(item.get('topic', [])) or '-'}")
    print(f"Skills      : {', '.join(item.get('skill', [])) or '-'}")
    print(f"Source type : {item.get('source_type')}")
    print(f"Path        : {item.get('obsidian_path')}")
    print(f"Link        : {item.get('obsidian_link')}")


def lookup_language_item(
    query: str,
    language: str | None,
    item_type: str | None,
    threshold: float,
    limit: int,
) -> None:
    config = load_config()
    db_path = Path(config["outputs"]["languageos_db"])

    conn = connect_db(db_path)
    query_normalized = normalize_text(query)

    print("LanguageOS Lookup")
    print("=" * 60)
    print(f"Query       : {query}")
    print(f"Normalized  : {query_normalized}")
    print(f"Language    : {language or 'any'}")
    print(f"Type        : {item_type or 'any'}")
    print(f"DB          : {db_path}")

    exact_matches = exact_lookup(
        conn=conn,
        query_normalized=query_normalized,
        language=language,
        item_type=item_type,
    )

    fuzzy_matches = fuzzy_lookup(
        conn=conn,
        query_normalized=query_normalized,
        language=language,
        item_type=item_type,
        threshold=threshold,
        limit=limit,
    )

    seen_ids: set[int] = set()

    print("\nExact matches")
    print("=" * 60)

    if exact_matches:
        for idx, item in enumerate(exact_matches, start=1):
            seen_ids.add(int(item["id"]))
            print_item(item, idx, "EXACT")
    else:
        print("No exact match found.")

    print("\nFuzzy matches")
    print("=" * 60)

    fuzzy_filtered = []

    for item in fuzzy_matches:
        item_id = int(item["id"])

        if item_id in seen_ids:
            continue

        fuzzy_filtered.append(item)
        seen_ids.add(item_id)

    if fuzzy_filtered:
        for idx, item in enumerate(fuzzy_filtered, start=1):
            print_item(item, idx, "FUZZY")
    else:
        print(f"No fuzzy match found above threshold {threshold}.")

    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lookup a word, phrase, or sentence in the LanguageOS SQLite database.",
    )

    parser.add_argument(
        "query",
        help="Text to search for.",
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
        "--threshold",
        type=float,
        default=70.0,
        help="Fuzzy match threshold from 0 to 100.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum fuzzy results.",
    )

    args = parser.parse_args()

    lookup_language_item(
        query=args.query,
        language=args.language,
        item_type=args.type,
        threshold=args.threshold,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
