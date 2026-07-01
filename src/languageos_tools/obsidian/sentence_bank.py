from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

CONFIG_PATH = Path("configs/languageos.config.json")


# Candidate JSON status -> Sentence Bank visible status
#
# In the candidate file, "duplicate" means:
# "This card already exists in Anki, so we skipped adding it again."
#
# In Sentence Bank, the learner only needs to know:
# "This sentence is already in Anki."
#
# Therefore both approved and duplicate are shown as "Added" in Obsidian.
STATUS_MAP = {
    "approved": "Added",
    "duplicate": "Added",
    "error": "Error",
}


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_candidates(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Candidate file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalize_text(text: str) -> str:
    """
    Normalize text for matching between candidate JSON and Markdown table.

    This helps when Obsidian wraps text visually or when there are extra spaces.
    """
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_header(text: str) -> str:
    """
    Normalize table headers.

    Examples:
    - "Anki?" -> "anki?"
    - "Anki ?" -> "anki?"
    - " Sentence " -> "sentence"
    """
    text = normalize_text(text)
    text = text.replace(" ", "")
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


def build_sentence_status_map(candidate_payload: dict) -> dict[str, str]:
    """
    Build mapping:

    normalized sentence/front text -> visible Anki? status for Sentence Bank

    Candidate status:
    - approved  -> Added
    - duplicate -> Added
    - error     -> Error
    """
    status_by_sentence: dict[str, str] = {}

    for candidate in candidate_payload.get("candidates", []):
        if candidate.get("source") != "Sentence Bank":
            continue

        front = candidate.get("front", "").strip()
        raw_status = candidate.get("status", "").strip().lower()

        if not front:
            continue

        mapped_status = STATUS_MAP.get(raw_status)

        if mapped_status is None:
            continue

        normalized_front = normalize_text(front)
        status_by_sentence[normalized_front] = mapped_status

    return status_by_sentence


def create_backup(source_path: Path, languageos_root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    backup_dir = languageos_root / "Inbox" / "Backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    backup_path = backup_dir / f"Sentence Bank.{timestamp}.md"

    shutil.copy2(source_path, backup_path)

    return backup_path


def find_column_indexes(headers: list[str]) -> tuple[int | None, int | None]:
    normalized_headers = [normalize_header(header) for header in headers]

    sentence_idx = None
    anki_idx = None

    for idx, header in enumerate(normalized_headers):
        if header == "sentence":
            sentence_idx = idx
        elif header == "anki?":
            anki_idx = idx

    return sentence_idx, anki_idx


def update_sentence_bank_anki_status(
    sentence_bank_path: Path,
    status_by_sentence: dict[str, str],
) -> int:
    """
    Update Sentence Bank markdown table.

    Rows with Anki? empty / Yes / Duplicate / Error / Added can be updated.

    Why update empty?
    - Current LanguageOS rule allows new rows to leave Anki? blank.
    - After pipeline runs, blank should become Added or Error.

    Why update Duplicate?
    - Older version wrote Duplicate into Obsidian.
    - New decision is to show Added instead.
    """
    original_lines = sentence_bank_path.read_text(encoding="utf-8").splitlines()

    updated_lines: list[str] = []

    headers: list[str] | None = None
    sentence_idx: int | None = None
    anki_idx: int | None = None
    inside_sentence_table = False

    update_count = 0
    matched_count = 0

    for line in original_lines:
        stripped = line.strip()

        if not stripped.startswith("|"):
            headers = None
            sentence_idx = None
            anki_idx = None
            inside_sentence_table = False
            updated_lines.append(line)
            continue

        cells = split_markdown_row(line)

        if not cells:
            updated_lines.append(line)
            continue

        if is_separator_row(cells):
            updated_lines.append(line)
            continue

        possible_sentence_idx, possible_anki_idx = find_column_indexes(cells)

        if possible_sentence_idx is not None and possible_anki_idx is not None:
            headers = cells
            sentence_idx = possible_sentence_idx
            anki_idx = possible_anki_idx
            inside_sentence_table = True
            updated_lines.append(line)
            continue

        if not inside_sentence_table:
            updated_lines.append(line)
            continue

        if headers is None or sentence_idx is None or anki_idx is None:
            updated_lines.append(line)
            continue

        if len(cells) != len(headers):
            updated_lines.append(line)
            continue

        sentence = normalize_text(cells[sentence_idx])
        current_anki_status = cells[anki_idx].strip()
        current_anki_status_lower = current_anki_status.lower()

        new_status = status_by_sentence.get(sentence)

        if new_status is None:
            updated_lines.append(line)
            continue

        matched_count += 1

        # Do not overwrite manual No.
        # No means the user does not want this sentence in Anki.
        if current_anki_status_lower == "no":
            updated_lines.append(line)
            continue

        # Update these states:
        # empty     -> Added / Error
        # Yes       -> Added / Error
        # Duplicate -> Added
        # Error     -> Added/Error if rerun after fix
        # Added     -> stays Added if no visible change
        allowed_to_update = current_anki_status_lower in {
            "",
            "yes",
            "duplicate",
            "error",
            "added",
        }

        if not allowed_to_update:
            updated_lines.append(line)
            continue

        if current_anki_status == new_status:
            updated_lines.append(line)
            continue

        cells[anki_idx] = new_status
        updated_lines.append(build_markdown_row(cells))
        update_count += 1

    sentence_bank_path.write_text(
        "\n".join(updated_lines) + "\n",
        encoding="utf-8",
    )

    print(f"[OK] Matching rows found: {matched_count}")

    return update_count


def main() -> None:
    print("Sync Sentence Bank Anki Status")
    print("=" * 60)

    config = load_config()

    languageos_root = Path(config["languageos_root"])
    sentence_bank_path = Path(config["required_paths"]["sentence_bank"])
    candidate_path = Path(config["outputs"]["anki_card_candidates"])

    if not sentence_bank_path.exists():
        raise FileNotFoundError(f"Sentence Bank not found: {sentence_bank_path}")

    candidate_payload = load_candidates(candidate_path)
    status_by_sentence = build_sentence_status_map(candidate_payload)

    print(f"[OK] Candidate statuses loaded: {len(status_by_sentence)}")

    if status_by_sentence:
        print("\nCandidate status map:")
        for sentence, status in status_by_sentence.items():
            print(f"- {status}: {sentence}")

    backup_path = create_backup(
        source_path=sentence_bank_path,
        languageos_root=languageos_root,
    )

    print(f"\n[OK] Backup created: {backup_path}")

    update_count = update_sentence_bank_anki_status(
        sentence_bank_path=sentence_bank_path,
        status_by_sentence=status_by_sentence,
    )

    print(f"[OK] Sentence Bank updated: {sentence_bank_path}")
    print(f"[OK] Rows updated: {update_count}")

    if update_count == 0:
        print("Hint: No visible changes were needed.")
        print(
            "Hint: If Obsidian is open, refresh/reopen the note after running this script."
        )


if __name__ == "__main__":
    main()
