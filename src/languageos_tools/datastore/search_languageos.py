from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path


CONFIG_PATH = Path("configs/languageos.config.json")


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


def escape_fts_phrase(text: str) -> str:
    return text.replace('"', '""').strip()


def tokenize_query(text: str) -> list[str]:
    tokens = re.findall(r"[\wÀ-ỹÄÖÜäöüß]+", text.lower(), flags=re.UNICODE)
    return [token for token in tokens if token.strip()]


def build_fts_queries(query: str) -> list[str]:
    """
    Build safe FTS5 queries.

    1. Exact phrase search:
       "guten morgen"

    2. Token AND search:
       "guten" AND "morgen"
    """
    queries: list[str] = []

    escaped_phrase = escape_fts_phrase(query)

    if escaped_phrase:
        queries.append(f'"{escaped_phrase}"')

    tokens = tokenize_query(query)

    if tokens:
        token_query = " AND ".join(f'"{escape_fts_phrase(token)}"' for token in tokens)

        if token_query not in queries:
            queries.append(token_query)

    return queries


def run_fts_query(
    conn: sqlite3.Connection,
    fts_query: str,
    language: str | None,
    doc_type: str | None,
    limit: int,
) -> list[dict]:
    sql = """
        SELECT
            rowid,
            item_id,
            doc_type,
            language,
            status,
            title,
            path,
            obsidian_link,
            snippet(search_documents_fts, -1, '[', ']', ' ... ', 20) AS snippet,
            rank
        FROM search_documents_fts
        WHERE search_documents_fts MATCH ?
    """

    params: list[object] = [fts_query]

    if language:
        sql += " AND language = ?"
        params.append(language)

    if doc_type:
        sql += " AND doc_type = ?"
        params.append(doc_type)

    sql += """
        ORDER BY rank
        LIMIT ?
    """
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()

    return [dict(row) for row in rows]


def search_languageos(
    query: str,
    language: str | None,
    doc_type: str | None,
    limit: int,
) -> None:
    config = load_config()
    db_path = Path(config["outputs"]["languageos_db"])

    conn = connect_db(db_path)

    print("LanguageOS Global Search")
    print("=" * 60)
    print(f"Query    : {query}")
    print(f"Language : {language or 'any'}")
    print(f"Type     : {doc_type or 'any'}")
    print(f"DB       : {db_path}")

    fts_queries = build_fts_queries(query)

    all_results: list[dict] = []
    seen_rowids: set[int] = set()

    for fts_query in fts_queries:
        try:
            results = run_fts_query(
                conn=conn,
                fts_query=fts_query,
                language=language,
                doc_type=doc_type,
                limit=limit,
            )
        except sqlite3.OperationalError as exc:
            print(f"\n[WARN] FTS query failed: {fts_query}")
            print(f"[WARN] {exc}")
            continue

        for result in results:
            rowid = int(result["rowid"])

            if rowid in seen_rowids:
                continue

            seen_rowids.add(rowid)
            result["fts_query"] = fts_query
            all_results.append(result)

        if len(all_results) >= limit:
            break

    print("\nResults")
    print("=" * 60)

    if not all_results:
        print("No global search result found.")
        conn.close()
        return

    for idx, result in enumerate(all_results[:limit], start=1):
        print(f"\n[RESULT #{idx}] {result.get('title')}")
        print("-" * 60)
        print(f"Matched by : {result.get('fts_query')}")
        print(f"Type       : {result.get('doc_type')}")
        print(f"Language   : {result.get('language')}")
        print(f"Status     : {result.get('status')}")
        print(f"Path       : {result.get('path')}")
        print(f"Link       : {result.get('obsidian_link')}")
        print("Snippet    :")
        print(result.get("snippet") or "")

    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search across all LanguageOS indexed documents using SQLite FTS5.",
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
        help="Optional document type filter.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum search results.",
    )

    args = parser.parse_args()

    search_languageos(
        query=args.query,
        language=args.language,
        doc_type=args.type,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()