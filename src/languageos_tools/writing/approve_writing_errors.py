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
        raise FileNotFoundError(f"Writing error candidate file not found: {path}")

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

    backup_path = backup_dir / f"Writing Error Log.{timestamp}.md"

    shutil.copy2(source_path, backup_path)

    return backup_path


def get_existing_error_keys(writing_error_log_path: Path) -> set[str]:
    """
    Return normalized existing writing error keys from all error tables.

    Key = wrong_sentence + correct_sentence
    """
    lines = writing_error_log_path.read_text(encoding="utf-8").splitlines()

    existing: set[str] = set()

    headers: list[str] | None = None
    wrong_idx: int | None = None
    correct_idx: int | None = None
    inside_error_table = False

    for line in lines:
        stripped = line.strip()

        if not stripped.startswith("|"):
            headers = None
            wrong_idx = None
            correct_idx = None
            inside_error_table = False
            continue

        cells = split_markdown_row(stripped)

        if not cells:
            continue

        if is_separator_row(cells):
            continue

        if "Wrong Sentence" in cells and "Correct Sentence" in cells:
            headers = cells
            wrong_idx = headers.index("Wrong Sentence")
            correct_idx = headers.index("Correct Sentence")
            inside_error_table = True
            continue

        if not inside_error_table:
            continue

        if headers is None or wrong_idx is None or correct_idx is None:
            continue

        if len(cells) != len(headers):
            continue

        wrong_sentence = cells[wrong_idx].strip()
        correct_sentence = cells[correct_idx].strip()

        if wrong_sentence and correct_sentence:
            key = build_error_key(
                wrong_sentence=wrong_sentence,
                correct_sentence=correct_sentence,
            )
            existing.add(key)

    return existing


def build_error_key(wrong_sentence: str, correct_sentence: str) -> str:
    return normalize_text(wrong_sentence) + " -> " + normalize_text(correct_sentence)


def candidate_to_row(candidate: dict) -> list[str]:
    return [
        candidate.get("date", "").strip(),
        candidate.get("wrong_sentence", "").strip(),
        candidate.get("correct_sentence", "").strip(),
        candidate.get("error_type", "").strip(),
        candidate.get("note", "").strip(),
    ]


def find_language_section(
    lines: list[str], language: str
) -> tuple[int | None, int | None]:
    """
    Find section boundaries for:

    ## English Errors

    or

    ## German Errors
    """
    target_heading = (
        "## English Errors" if language == "english" else "## German Errors"
    )

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


def find_table_insert_index(
    lines: list[str], section_start: int, section_end: int
) -> int | None:
    """
    Find where to insert a new row in the writing error table.

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

        if "Wrong Sentence" in cells and "Correct Sentence" in cells:
            table_started = True
            last_table_line_idx = idx
            continue

        if table_started:
            last_table_line_idx = idx

    if last_table_line_idx is None:
        return None

    return last_table_line_idx + 1


def append_writing_error_row(
    writing_error_log_path: Path,
    candidate: dict,
) -> None:
    language = candidate.get("language", "english").strip().lower()

    if language not in {"english", "german"}:
        language = "english"

    lines = writing_error_log_path.read_text(encoding="utf-8").splitlines()

    section_start, section_end = find_language_section(lines, language)

    if section_start is None or section_end is None:
        raise RuntimeError(
            f"Could not find writing error section for language: {language}"
        )

    insert_idx = find_table_insert_index(
        lines=lines,
        section_start=section_start,
        section_end=section_end,
    )

    if insert_idx is None:
        raise RuntimeError(
            f"Could not find writing error table for language: {language}"
        )

    new_row = build_markdown_row(candidate_to_row(candidate))

    lines.insert(insert_idx, new_row)

    writing_error_log_path.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def approve_writing_error_candidates(
    config: dict, payload: dict
) -> tuple[int, int, int]:
    languageos_root = Path(config["languageos_root"])
    writing_error_log_path = Path(config["required_paths"]["writing_error_log"])

    if not writing_error_log_path.exists():
        raise FileNotFoundError(
            f"Writing Error Log not found: {writing_error_log_path}"
        )

    backup_path = create_backup(
        source_path=writing_error_log_path,
        languageos_root=languageos_root,
    )

    print(f"[OK] Backup created: {backup_path}")

    existing_keys = get_existing_error_keys(writing_error_log_path)

    approved_count = 0
    duplicate_count = 0
    error_count = 0

    for candidate in payload.get("candidates", []):
        if candidate.get("status") != "pending_review":
            continue

        wrong_sentence = candidate.get("wrong_sentence", "").strip()
        correct_sentence = candidate.get("correct_sentence", "").strip()

        if not wrong_sentence:
            candidate["status"] = "error"
            candidate["error"] = "Missing wrong_sentence"
            error_count += 1
            print("[ERROR] Candidate missing wrong_sentence")
            continue

        if not correct_sentence:
            candidate["status"] = "error"
            candidate["error"] = "Missing correct_sentence"
            error_count += 1
            print("[ERROR] Candidate missing correct_sentence")
            continue

        error_key = build_error_key(
            wrong_sentence=wrong_sentence,
            correct_sentence=correct_sentence,
        )

        if error_key in existing_keys:
            candidate["status"] = "duplicate"
            candidate["duplicate_reason"] = "Already exists in Writing Error Log"
            duplicate_count += 1
            print(f"[SKIP] Duplicate writing error: {wrong_sentence}")
            continue

        try:
            append_writing_error_row(
                writing_error_log_path=writing_error_log_path,
                candidate=candidate,
            )

            existing_keys.add(error_key)

            candidate["status"] = "approved"
            candidate["target_file"] = str(writing_error_log_path)
            approved_count += 1

            print(f"[OK] Added writing error: {wrong_sentence}")

        except Exception as exc:
            candidate["status"] = "error"
            candidate["error"] = str(exc)
            error_count += 1

            print(f"[ERROR] Failed to add writing error: {wrong_sentence}")
            print(f"        {exc}")

    return approved_count, duplicate_count, error_count


def main() -> None:
    print("Approve Writing Error Candidates")
    print("=" * 60)

    config = load_config()

    candidate_path = Path(config["outputs"]["writing_error_candidates"])
    payload = load_candidates(candidate_path)

    approved_count, duplicate_count, error_count = approve_writing_error_candidates(
        config=config,
        payload=payload,
    )

    save_candidates(candidate_path, payload)

    print("\nSummary")
    print("-" * 60)
    print(f"[OK] Approved writing errors: {approved_count}")
    print(f"[SKIP] Duplicates: {duplicate_count}")
    print(f"[ERROR] Errors: {error_count}")
    print(f"[OK] Updated candidate file: {candidate_path}")


if __name__ == "__main__":
    main()
