from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

CONFIG_PATH = Path("configs/languageos.config.json")


ACTIVITY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS item_activity (
    item_key TEXT PRIMARY KEY,

    type TEXT NOT NULL,
    language TEXT NOT NULL,
    normalized TEXT NOT NULL,

    access_count INTEGER NOT NULL DEFAULT 0,
    last_accessed_at TEXT,

    review_count INTEGER NOT NULL DEFAULT 0,
    last_reviewed_at TEXT,

    review_status TEXT NOT NULL DEFAULT 'unreviewed',
    review_priority TEXT NOT NULL DEFAULT 'normal',
    stale_after_days INTEGER NOT NULL DEFAULT 14,

    created_at TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_item_activity_type_language
ON item_activity(type, language);

CREATE INDEX IF NOT EXISTS idx_item_activity_access_count
ON item_activity(access_count);

CREATE INDEX IF NOT EXISTS idx_item_activity_last_accessed_at
ON item_activity(last_accessed_at);

CREATE INDEX IF NOT EXISTS idx_item_activity_review_status
ON item_activity(review_status);
"""


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


def init_activity_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(ACTIVITY_SCHEMA_SQL)
    conn.commit()


def normalize_text(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[“”\"'`]", "", text)
    text = re.sub(r"[.!?。！？]+$", "", text)
    text = text.strip()

    return text


def make_item_key(item_type: str, language: str, normalized: str) -> str:
    return f"{item_type}|{language}|{normalized}"


def make_item_key_from_row(row: sqlite3.Row | dict) -> str:
    return make_item_key(
        item_type=str(row["type"]),
        language=str(row["language"]),
        normalized=str(row["normalized"]),
    )


def ensure_activity_row(conn: sqlite3.Connection, item: sqlite3.Row | dict) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    item_key = make_item_key_from_row(item)

    conn.execute(
        """
        INSERT OR IGNORE INTO item_activity (
            item_key,
            type,
            language,
            normalized,
            access_count,
            review_count,
            review_status,
            review_priority,
            stale_after_days,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, 0, 0, 'unreviewed', 'normal', 14, ?, ?)
        """,
        (
            item_key,
            item["type"],
            item["language"],
            item["normalized"],
            now,
            now,
        ),
    )


def compute_review_status(
    access_count: int,
    last_accessed_at: str | None,
    item_status: str,
    stale_after_days: int,
) -> str:
    item_status = (item_status or "").strip().lower()

    if item_status in {"ignored", "archived"}:
        return "ignored"

    if access_count <= 0 or not last_accessed_at:
        return "unreviewed"

    try:
        last_accessed = datetime.fromisoformat(last_accessed_at)
    except ValueError:
        return "active"

    days_since_access = (datetime.now() - last_accessed).days

    if days_since_access >= stale_after_days:
        return "stale"

    return "active"


def touch_item(conn: sqlite3.Connection, item: sqlite3.Row | dict) -> dict:
    init_activity_schema(conn)
    ensure_activity_row(conn, item)

    now = datetime.now().isoformat(timespec="seconds")
    item_key = make_item_key_from_row(item)

    current = conn.execute(
        """
        SELECT *
        FROM item_activity
        WHERE item_key = ?
        """,
        (item_key,),
    ).fetchone()

    access_count = int(current["access_count"]) + 1
    stale_after_days = int(current["stale_after_days"] or 14)

    review_status = compute_review_status(
        access_count=access_count,
        last_accessed_at=now,
        item_status=str(item["status"]),
        stale_after_days=stale_after_days,
    )

    conn.execute(
        """
        UPDATE item_activity
        SET
            access_count = ?,
            last_accessed_at = ?,
            review_status = ?,
            updated_at = ?
        WHERE item_key = ?
        """,
        (
            access_count,
            now,
            review_status,
            now,
            item_key,
        ),
    )

    conn.commit()

    return {
        "item_key": item_key,
        "access_count": access_count,
        "last_accessed_at": now,
        "review_status": review_status,
    }


def find_exact_items(
    conn: sqlite3.Connection,
    query: str,
    language: str | None = None,
    item_type: str | None = None,
) -> list[sqlite3.Row]:
    normalized = normalize_text(query)

    sql = """
        SELECT *
        FROM items
        WHERE normalized = ?
    """

    params: list[object] = [normalized]

    if language:
        sql += " AND language = ?"
        params.append(language)

    if item_type:
        sql += " AND type = ?"
        params.append(item_type)

    sql += """
        ORDER BY
            CASE type
                WHEN 'vocabulary' THEN 1
                WHEN 'sentence' THEN 2
                WHEN 'grammar' THEN 3
                ELSE 9
            END,
            language,
            text
    """

    return list(conn.execute(sql, params).fetchall())


def find_contains_items(
    conn: sqlite3.Connection,
    query: str,
    language: str | None = None,
    item_type: str | None = None,
    limit: int = 10,
) -> list[sqlite3.Row]:
    normalized = normalize_text(query)

    sql = """
        SELECT *
        FROM items
        WHERE normalized LIKE ?
    """

    params: list[object] = [f"%{normalized}%"]

    if language:
        sql += " AND language = ?"
        params.append(language)

    if item_type:
        sql += " AND type = ?"
        params.append(item_type)

    sql += """
        ORDER BY seen_count DESC, text
        LIMIT ?
    """
    params.append(limit)

    return list(conn.execute(sql, params).fetchall())


def touch_by_query(
    query: str,
    language: str | None = None,
    item_type: str | None = None,
) -> dict:
    config = load_config()
    db_path = get_db_path(config)

    conn = connect_db(db_path)
    init_activity_schema(conn)

    exact_items = find_exact_items(
        conn=conn,
        query=query,
        language=language,
        item_type=item_type,
    )

    touched: list[dict] = []

    if exact_items:
        for item in exact_items:
            activity = touch_item(conn, item)
            touched.append(
                {
                    "match_type": "exact",
                    "text": item["text"],
                    "type": item["type"],
                    "language": item["language"],
                    "status": item["status"],
                    "anki_status": item["anki_status"],
                    "obsidian_path": item["obsidian_path"],
                    "obsidian_link": item["obsidian_link"],
                    "activity": activity,
                }
            )

        conn.close()

        return {
            "query": query,
            "db_path": str(db_path),
            "matched": len(touched),
            "touched": touched,
            "fallback_candidates": [],
        }

    fallback_items = find_contains_items(
        conn=conn,
        query=query,
        language=language,
        item_type=item_type,
    )

    fallback_candidates = [
        {
            "text": item["text"],
            "type": item["type"],
            "language": item["language"],
            "status": item["status"],
            "obsidian_path": item["obsidian_path"],
            "obsidian_link": item["obsidian_link"],
        }
        for item in fallback_items
    ]

    conn.close()

    return {
        "query": query,
        "db_path": str(db_path),
        "matched": 0,
        "touched": [],
        "fallback_candidates": fallback_candidates,
    }


def get_activity_report(
    view: str,
    language: str | None = None,
    item_type: str | None = None,
    limit: int = 20,
) -> dict:
    config = load_config()
    db_path = get_db_path(config)

    conn = connect_db(db_path)
    init_activity_schema(conn)

    base_select = """
        SELECT
            i.type,
            i.language,
            i.text,
            i.normalized,
            i.status,
            i.anki_status,
            i.level,
            i.seen_count,
            i.last_seen,
            i.obsidian_path,
            i.obsidian_link,

            COALESCE(a.access_count, 0) AS access_count,
            a.last_accessed_at,
            COALESCE(a.review_count, 0) AS review_count,
            a.last_reviewed_at,
            COALESCE(a.review_status, 'unreviewed') AS review_status,
            COALESCE(a.review_priority, 'normal') AS review_priority,
            COALESCE(a.stale_after_days, 14) AS stale_after_days
        FROM items i
        LEFT JOIN item_activity a
          ON a.item_key = i.type || '|' || i.language || '|' || i.normalized
        WHERE 1 = 1
    """

    params: list[object] = []

    if language:
        base_select += " AND i.language = ?"
        params.append(language)

    if item_type:
        base_select += " AND i.type = ?"
        params.append(item_type)

    if view == "never-accessed":
        sql = (
            base_select
            + """
            AND COALESCE(a.access_count, 0) = 0
            ORDER BY i.seen_count DESC, i.text
            LIMIT ?
        """
        )

    elif view == "least-accessed":
        sql = (
            base_select
            + """
            ORDER BY COALESCE(a.access_count, 0) ASC, i.seen_count DESC, i.text
            LIMIT ?
        """
        )

    elif view == "oldest-accessed":
        sql = (
            base_select
            + """
            AND a.last_accessed_at IS NOT NULL
            ORDER BY a.last_accessed_at ASC
            LIMIT ?
        """
        )

    elif view == "recently-accessed":
        sql = (
            base_select
            + """
            AND a.last_accessed_at IS NOT NULL
            ORDER BY a.last_accessed_at DESC
            LIMIT ?
        """
        )

    elif view == "high-seen-low-access":
        sql = (
            base_select
            + """
            AND i.seen_count >= 2
            AND COALESCE(a.access_count, 0) <= 1
            ORDER BY i.seen_count DESC, COALESCE(a.access_count, 0) ASC
            LIMIT ?
        """
        )

    elif view == "stale-learning":
        cutoff = (datetime.now() - timedelta(days=14)).isoformat(timespec="seconds")
        sql = (
            base_select
            + """
            AND i.status = 'learning'
            AND (
                a.last_accessed_at IS NULL
                OR a.last_accessed_at <= ?
            )
            ORDER BY
                CASE WHEN a.last_accessed_at IS NULL THEN 0 ELSE 1 END,
                a.last_accessed_at ASC,
                i.seen_count DESC
            LIMIT ?
        """
        )
        params.append(cutoff)

    else:
        conn.close()
        raise ValueError(
            "Unknown view. Use one of: "
            "never-accessed, least-accessed, oldest-accessed, "
            "recently-accessed, high-seen-low-access, stale-learning"
        )

    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    return {
        "view": view,
        "language": language or "any",
        "type": item_type or "any",
        "limit": limit,
        "db_path": str(db_path),
        "items": [dict(row) for row in rows],
    }


def print_touch_result(payload: dict) -> None:
    print("Touch Language Item")
    print("=" * 60)
    print(f"Query : {payload['query']}")
    print(f"DB    : {payload['db_path']}")

    if payload["matched"] == 0:
        print("\nNo exact item was touched.")

        if payload["fallback_candidates"]:
            print("\nPossible candidates:")
            print("-" * 60)

            for idx, item in enumerate(payload["fallback_candidates"], start=1):
                print(f"[{idx}] {item['text']}")
                print(f"    Type     : {item['type']}")
                print(f"    Language : {item['language']}")
                print(f"    Status   : {item['status']}")
                print(f"    Path     : {item['obsidian_path']}")
                print(f"    Link     : {item['obsidian_link']}")
        return

    print(f"\nTouched items: {payload['matched']}")
    print("-" * 60)

    for item in payload["touched"]:
        activity = item["activity"]

        print(f"\n{item['text']}")
        print(f"Type           : {item['type']}")
        print(f"Language       : {item['language']}")
        print(f"Status         : {item['status']}")
        print(f"Anki           : {item['anki_status']}")
        print(f"Path           : {item['obsidian_path']}")
        print(f"Link           : {item['obsidian_link']}")
        print(f"Access count   : {activity['access_count']}")
        print(f"Last accessed  : {activity['last_accessed_at']}")
        print(f"Review status  : {activity['review_status']}")


def print_report(payload: dict) -> None:
    print("LanguageOS Activity Report")
    print("=" * 60)
    print(f"View     : {payload['view']}")
    print(f"Language : {payload['language']}")
    print(f"Type     : {payload['type']}")
    print(f"Limit    : {payload['limit']}")
    print(f"DB       : {payload['db_path']}")

    print("\nResults")
    print("=" * 60)

    if not payload["items"]:
        print("No items found for this view.")
        return

    for idx, item in enumerate(payload["items"], start=1):
        print(f"\n[{idx}] {item['text']}")
        print("-" * 60)
        print(f"Type             : {item['type']}")
        print(f"Language         : {item['language']}")
        print(f"Status           : {item['status']}")
        print(f"Anki             : {item['anki_status']}")
        print(f"Level            : {item['level']}")
        print(f"Seen count       : {item['seen_count']}")
        print(f"Last seen        : {item['last_seen']}")
        print(f"Access count     : {item['access_count']}")
        print(f"Last accessed    : {item['last_accessed_at'] or '—'}")
        print(f"Review status    : {item['review_status']}")
        print(f"Review priority  : {item['review_priority']}")
        print(f"Path             : {item['obsidian_path']}")
        print(f"Link             : {item['obsidian_link']}")


def init_activity_tracking() -> dict:
    config = load_config()
    db_path = get_db_path(config)

    conn = connect_db(db_path)
    init_activity_schema(conn)

    conn.close()

    return {
        "db_path": str(db_path),
        "status": "ok",
    }
