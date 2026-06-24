from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path


CONFIG_PATH = Path("configs/languageos.config.json")


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_candidates(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Vocabulary candidate file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_candidates(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def normalize_text(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text.lower()


def split_markdown_row(line: str) -> list[str]:
    line = line.strip()

    if not line.startswith("|") or not line.endswith("|"):
        return []

    return [cell.strip() for cell in line.strip("|").split("|")]


def build_markdown_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def is_separator_row(cells: list[str]) -> bool:
    if not cells:
        return False

    for cell in cells:
        normalized = cell.replace(" ", "")
        if not normalized:
            return False

        if set(normalized) - {"-", ":"}:
            return False

    return True


def create_backup(source_path: Path, languageos_root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    backup_dir = languageos_root / "Inbox" / "Backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    backup_path = backup_dir / f"Vocabulary Inbox.{timestamp}.md"

    shutil.copy2(source_path, backup_path)

    return backup_path


def get_existing_vocabulary_keys(vocabulary_inbox_path: Path) -> set[str]:
    """
    Return normalized existing words/phrases from all vocabulary tables.
    """
    lines = vocabulary_inbox_path.read_text(encoding="utf-8").splitlines()

    existing: set[str] = set()
    headers: list[str] | None = None
    word_idx: int | None = None
    inside_vocab_table = False

    for line in lines:
        stripped = line.strip()

        if not stripped.startswith("|"):
            headers = None
            word_idx = None
            inside_vocab_table = False
            continue

        cells = split_markdown_row(stripped)

        if not cells:
            continue

        if is_separator_row(cells):
            continue

        if "Word / Phrase" in cells:
            headers = cells
            word_idx = headers.index("Word / Phrase")
            inside_vocab_table = True
            continue

        if not inside_vocab_table:
            continue

        if headers is None or word_idx is None:
            continue

        if len(cells) != len(headers):
            continue

        word_or_phrase = cells[word_idx].strip()

        if word_or_phrase:
            existing.add(normalize_text(word_or_phrase))

    return existing


def candidate_to_row(candidate: dict) -> list[str]:
    return [
        candidate.get("word_or_phrase", "").strip(),
        candidate.get("meaning", "").strip(),
        candidate.get("example_sentence", "").strip(),
        candidate.get("source", "").strip(),
    ]


def find_language_section(lines: list[str], language: str) -> tuple[int | None, int | None]:
    """
    Find section boundaries for:

    ## English

    or

    ## German

    Returns:
    (section_start_idx, section_end_idx)

    section_end_idx is the line index where the next section starts,
    or len(lines) if this is the last section.
    """
    target_heading = "## English" if language == "english" else "## German"

    start_idx = None

    for idx, line in enumerate(lines):
        if line.strip() == target_heading:
            start_idx = idx
            break

    if start_idx is None:
        return None, None

    end_idx = len(lines)

    for idx in range(start_idx + 1, len(lines)):
        if lines[idx].strip().startswith("## "):
            end_idx = idx
            break

    return start_idx, end_idx


def find_table_insert_index(lines: list[str], section_start: int, section_end: int) -> int | None:
    """
    Find where to insert a new row in the vocabulary table.

    We insert after the last data row of the table.
    """
    table_started = False
    last_table_line_idx = None

    for idx in range(section_start + 1, section_end):
        stripped = lines[idx].strip()

        if not stripped.startswith("|"):
            if table_started:
                break
            continue

        cells = split_markdown_row(stripped)

        if not cells:
            continue

        if "Word / Phrase" in cells:
            table_started = True
            last_table_line_idx = idx
            continue

        if table_started:
            last_table_line_idx = idx

    if last_table_line_idx is None:
        return None

    return last_table_line_idx + 1


def append_vocabulary_row(
    vocabulary_inbox_path: Path,
    candidate: dict,
) -> None:
    language = candidate.get("language", "english").strip().lower()

    if language not in {"english", "german"}:
        language = "english"

    lines = vocabulary_inbox_path.read_text(encoding="utf-8").splitlines()

    section_start, section_end = find_language_section(lines, language)

    if section_start is None or section_end is None:
        raise RuntimeError(f"Could not find vocabulary section for language: {language}")

    insert_idx = find_table_insert_index(
        lines=lines,
        section_start=section_start,
        section_end=section_end,
    )

    if insert_idx is None:
        raise RuntimeError(f"Could not find vocabulary table for language: {language}")

    new_row = build_markdown_row(candidate_to_row(candidate))

    lines.insert(insert_idx, new_row)

    vocabulary_inbox_path.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def approve_vocabulary_candidates(config: dict, payload: dict) -> tuple[int, int, int]:
    languageos_root = Path(config["languageos_root"])
    vocabulary_inbox_path = Path(config["required_paths"]["vocabulary_inbox"])

    if not vocabulary_inbox_path.exists():
        raise FileNotFoundError(f"Vocabulary Inbox not found: {vocabulary_inbox_path}")

    backup_path = create_backup(
        source_path=vocabulary_inbox_path,
        languageos_root=languageos_root,
    )

    print(f"[OK] Backup created: {backup_path}")

    existing_keys = get_existing_vocabulary_keys(vocabulary_inbox_path)

    approved_count = 0
    duplicate_count = 0
    error_count = 0

    for candidate in payload.get("candidates", []):
        if candidate.get("status") != "pending_review":
            continue

        word_or_phrase = candidate.get("word_or_phrase", "").strip()

        if not word_or_phrase:
            candidate["status"] = "error"
            candidate["error"] = "Missing word_or_phrase"
            error_count += 1
            print("[ERROR] Candidate missing word_or_phrase")
            continue

        normalized_key = normalize_text(word_or_phrase)

        if normalized_key in existing_keys:
            candidate["status"] = "duplicate"
            candidate["duplicate_reason"] = "Already exists in Vocabulary Inbox"
            duplicate_count += 1
            print(f"[SKIP] Duplicate vocabulary: {word_or_phrase}")
            continue

        try:
            append_vocabulary_row(
                vocabulary_inbox_path=vocabulary_inbox_path,
                candidate=candidate,
            )

            existing_keys.add(normalized_key)

            candidate["status"] = "approved"
            candidate["target_file"] = str(vocabulary_inbox_path)
            approved_count += 1

            print(f"[OK] Added vocabulary: {word_or_phrase}")

        except Exception as exc:
            candidate["status"] = "error"
            candidate["error"] = str(exc)
            error_count += 1

            print(f"[ERROR] Failed to add vocabulary: {word_or_phrase}")
            print(f"        {exc}")

    return approved_count, duplicate_count, error_count


def main() -> None:
    print("Approve Vocabulary Candidates")
    print("=" * 60)

    config = load_config()

    candidate_path = Path(config["outputs"]["vocabulary_candidates"])
    payload = load_candidates(candidate_path)

    approved_count, duplicate_count, error_count = approve_vocabulary_candidates(
        config=config,
        payload=payload,
    )

    save_candidates(candidate_path, payload)

    print("\nSummary")
    print("-" * 60)
    print(f"[OK] Approved vocabulary: {approved_count}")
    print(f"[SKIP] Duplicates: {duplicate_count}")
    print(f"[ERROR] Errors: {error_count}")
    print(f"[OK] Updated candidate file: {candidate_path}")


if __name__ == "__main__":
    main()