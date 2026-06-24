from __future__ import annotations

import json
from pathlib import Path


CONFIG_PATH = Path("configs/languageos.config.json")


SKIP_ANKI_STATUSES = {
    "no",
    "added",
    "duplicate",
    "error",
}


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def split_markdown_row(line: str) -> list[str]:
    line = line.strip()

    if not line.startswith("|") or not line.endswith("|"):
        return []

    return [cell.strip() for cell in line.strip("|").split("|")]


def is_separator_row(cells: list[str]) -> bool:
    return all(set(cell.replace(" ", "")) <= {"-"} for cell in cells if cell)


def build_back_text(meaning: str, note: str) -> str:
    parts = []

    if meaning:
        parts.append(meaning)

    if note:
        parts.append(note)

    return "\n\n".join(parts)


def detect_language(section_name: str | None) -> str:
    if section_name and "German" in section_name:
        return "german"

    return "english"


def should_create_anki_candidate(anki_value: str) -> bool:
    """
    Decide whether a Sentence Bank row should become an Anki candidate.

    Current LanguageOS rule:

    - Empty Anki? cell  -> create candidate automatically
    - Yes              -> create candidate
    - No               -> skip
    - Added            -> skip
    - Duplicate        -> skip
    - Error            -> skip

    This lets the user add new sentences quickly and leave Anki? blank.
    If the user does not want a card, they should explicitly write No.
    """
    normalized = anki_value.strip().lower()

    if normalized == "":
        return True

    if normalized == "yes":
        return True

    if normalized in SKIP_ANKI_STATUSES:
        return False

    # Unknown status should be skipped for safety.
    return False


def extract_anki_candidates_from_sentence_bank(sentence_bank_path: Path) -> list[dict]:
    lines = sentence_bank_path.read_text(encoding="utf-8").splitlines()

    candidates: list[dict] = []
    current_section: str | None = None
    headers: list[str] | None = None

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("## "):
            current_section = stripped.replace("##", "").strip()
            headers = None
            continue

        if not stripped.startswith("|"):
            continue

        cells = split_markdown_row(stripped)

        if not cells:
            continue

        if is_separator_row(cells):
            continue

        if headers is None:
            headers = cells
            continue

        if len(cells) != len(headers):
            continue

        row = dict(zip(headers, cells))

        sentence = row.get("Sentence", "").strip()
        meaning = row.get("Meaning", "").strip()
        note = row.get("Note", "").strip()
        anki_value = row.get("Anki?", "").strip()

        if not sentence:
            continue

        if not should_create_anki_candidate(anki_value):
            continue

        language = detect_language(current_section)

        candidate = {
            "source": "Sentence Bank",
            "language": language,
            "card_type": "sentence",
            "front": sentence,
            "back": build_back_text(meaning=meaning, note=note),
            "tags": [language, "sentence", "candidate"],
            "status": "pending_review",
        }

        candidates.append(candidate)

    return candidates


def save_candidates(candidates: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "schema_version": "0.2",
        "count": len(candidates),
        "rules": {
            "empty_anki_cell": "create_candidate",
            "yes": "create_candidate",
            "no": "skip",
            "added": "skip",
            "duplicate": "skip",
            "error": "skip",
        },
        "candidates": candidates,
    }

    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    config = load_config()

    sentence_bank_path = Path(config["required_paths"]["sentence_bank"])
    output_path = Path(config["outputs"]["anki_card_candidates"])

    print("Anki Card Candidate Generator")
    print("=" * 60)

    if not sentence_bank_path.exists():
        raise FileNotFoundError(f"Sentence Bank not found: {sentence_bank_path}")

    candidates = extract_anki_candidates_from_sentence_bank(sentence_bank_path)
    save_candidates(candidates, output_path)

    print(f"[OK] Sentence Bank: {sentence_bank_path}")
    print(f"[OK] Candidates found: {len(candidates)}")
    print(f"[OK] Output: {output_path}")

    if candidates:
        print("\nCandidates:")
        for idx, candidate in enumerate(candidates, start=1):
            print(f"{idx}. {candidate['front']}")
    else:
        print("\nNo candidates found.")
        print("Hint: Add a new sentence with Anki? blank or Anki? = Yes.")


if __name__ == "__main__":
    main()