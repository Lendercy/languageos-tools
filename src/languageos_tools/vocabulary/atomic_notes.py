from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

CONFIG_PATH = Path("configs/languageos.config.json")


LANGUAGE_FOLDER_MAP = {
    "english": "English",
    "german": "German",
}


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalize_text(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text.lower()


def sanitize_filename(text: str) -> str:
    text = text.strip()

    invalid_chars = r'<>:"/\|?*'
    for char in invalid_chars:
        text = text.replace(char, " ")

    text = re.sub(r"\s+", " ", text)
    text = text.strip(" .")

    if not text:
        return "untitled"

    return text[:120]


def split_markdown_row(line: str) -> list[str]:
    line = line.strip()

    if not line.startswith("|") or not line.endswith("|"):
        return []

    return [cell.strip() for cell in line.strip("|").split("|")]


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


def detect_source_type(source: str) -> str:
    source_normalized = source.strip().lower()

    if "stt" in source_normalized or "transcript" in source_normalized:
        return "stt"

    if "tts" in source_normalized:
        return "tts"

    if "writing" in source_normalized:
        return "writing"

    if "dictionary" in source_normalized:
        return "dictionary"

    if "reading" in source_normalized:
        return "reading"

    if source_normalized:
        return "manual"

    return "manual"


def detect_language_from_section(section_name: str | None) -> str:
    if section_name and "german" in section_name.lower():
        return "german"

    return "english"


def extract_vocabulary_rows(vocabulary_inbox_path: Path) -> list[dict]:
    lines = vocabulary_inbox_path.read_text(encoding="utf-8").splitlines()

    rows: list[dict] = []

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

        word_or_phrase = row.get("Word / Phrase", "").strip()
        meaning = row.get("Meaning", "").strip()
        example_sentence = row.get("Example Sentence", "").strip()
        source = row.get("Source", "").strip()

        if not word_or_phrase:
            continue

        language = detect_language_from_section(current_section)

        rows.append(
            {
                "language": language,
                "word_or_phrase": word_or_phrase,
                "meaning": meaning,
                "example_sentence": example_sentence,
                "source": source,
                "source_type": detect_source_type(source),
            }
        )

    return rows


def vocabulary_note_path(obsidian_vault: Path, language: str, term: str) -> Path:
    folder_name = LANGUAGE_FOLDER_MAP.get(language, "English")
    safe_name = sanitize_filename(term)

    return obsidian_vault / "Vocabulary" / folder_name / f"{safe_name}.md"


def yaml_list(items: list[str], indent: int = 2) -> str:
    prefix = " " * indent
    return "\n".join(f"{prefix}- {item}" for item in items)


def build_new_vocabulary_note(candidate: dict) -> str:
    today = date.today().isoformat()

    language = candidate["language"]
    term = candidate["word_or_phrase"]
    normalized = normalize_text(term)
    meaning = candidate.get("meaning", "")
    example_sentence = candidate.get("example_sentence", "")
    source = candidate.get("source", "")
    source_type = candidate.get("source_type", "manual")

    topic = ["vocabulary"]
    skill = ["vocabulary"]

    lines: list[str] = []

    lines.append("---")
    lines.append("type: vocabulary")
    lines.append(f"language: {language}")
    lines.append(f"term: {term}")
    lines.append(f"normalized: {normalized}")
    lines.append("status: learning")
    lines.append("anki_status: none")
    lines.append("anki_note_id:")
    lines.append("topic:")
    lines.append(yaml_list(topic))
    lines.append("level: unknown")
    lines.append("part_of_speech: unknown")
    lines.append("skill:")
    lines.append(yaml_list(skill))
    lines.append(f"source_type: {source_type}")
    lines.append(f"source: {source}")
    lines.append("seen_count: 1")
    lines.append(f"first_seen: {today}")
    lines.append(f"last_seen: {today}")
    lines.append("difficulty: unknown")
    lines.append("confidence: medium")
    lines.append(f"created_at: {today}")
    lines.append(f"updated_at: {today}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {term}")
    lines.append("")
    lines.append("🟡 Status: learning  ")
    lines.append("📌 Anki: none  ")
    lines.append("🔁 Seen: 1")
    lines.append("")
    lines.append("## Meaning")
    lines.append("")
    lines.append(meaning if meaning else "- ")
    lines.append("")
    lines.append("## Contexts")
    lines.append("")
    if example_sentence:
        lines.append(f"- {source or 'Vocabulary Inbox'}")
        lines.append(f"  - {example_sentence}")
    else:
        lines.append("- Vocabulary Inbox")
    lines.append("")
    lines.append("## Example Sentences")
    lines.append("")
    if example_sentence:
        lines.append(f"- {example_sentence}")
    else:
        lines.append("- ")
    lines.append("")
    lines.append("## Related")
    lines.append("")
    lines.append("- ")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- ")

    return "\n".join(lines) + "\n"


def read_frontmatter_and_body(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text

    parts = text.split("---", 2)

    if len(parts) < 3:
        return {}, text

    frontmatter_text = parts[1]
    body = parts[2].lstrip("\n")

    data: dict[str, str] = {}

    for line in frontmatter_text.splitlines():
        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()

    return data, body


def update_existing_vocabulary_note(note_path: Path, candidate: dict) -> bool:
    """
    Update an existing vocabulary note lightly.

    Current v0.1 behavior:
    - increase seen_count
    - update last_seen / updated_at
    - append context if the example sentence is not already in the note

    Returns True if file content changed.
    """
    original_text = note_path.read_text(encoding="utf-8")
    frontmatter, body = read_frontmatter_and_body(original_text)

    today = date.today().isoformat()
    example_sentence = candidate.get("example_sentence", "").strip()
    source = candidate.get("source", "").strip() or "Vocabulary Inbox"

    old_seen_count_text = frontmatter.get("seen_count", "1")

    try:
        old_seen_count = int(old_seen_count_text)
    except ValueError:
        old_seen_count = 1

    new_seen_count = old_seen_count + 1

    updated_text = original_text

    updated_text = re.sub(
        r"seen_count:\s*\d+",
        f"seen_count: {new_seen_count}",
        updated_text,
        count=1,
    )

    updated_text = re.sub(
        r"last_seen:\s*.*",
        f"last_seen: {today}",
        updated_text,
        count=1,
    )

    updated_text = re.sub(
        r"updated_at:\s*.*",
        f"updated_at: {today}",
        updated_text,
        count=1,
    )

    updated_text = re.sub(
        r"🔁 Seen:\s*\d+",
        f"🔁 Seen: {new_seen_count}",
        updated_text,
        count=1,
    )

    if example_sentence and example_sentence not in updated_text:
        context_block = f"\n- {source}\n  - {example_sentence}"

        if "## Contexts" in updated_text:
            updated_text = updated_text.replace(
                "## Example Sentences",
                context_block + "\n\n## Example Sentences",
                1,
            )

        if "## Example Sentences" in updated_text:
            updated_text = updated_text.replace(
                "## Related",
                f"- {example_sentence}\n\n## Related",
                1,
            )

    if updated_text != original_text:
        note_path.write_text(updated_text, encoding="utf-8")
        return True

    return False


def build_vocabulary_atomic_notes(config: dict) -> tuple[int, int, int]:
    obsidian_vault = Path(config["obsidian_vault"])
    vocabulary_inbox_path = Path(config["required_paths"]["vocabulary_inbox"])

    if not vocabulary_inbox_path.exists():
        raise FileNotFoundError(f"Vocabulary Inbox not found: {vocabulary_inbox_path}")

    rows = extract_vocabulary_rows(vocabulary_inbox_path)

    created_count = 0
    updated_count = 0
    skipped_count = 0

    for row in rows:
        term = row["word_or_phrase"]
        language = row["language"]

        note_path = vocabulary_note_path(
            obsidian_vault=obsidian_vault,
            language=language,
            term=term,
        )

        note_path.parent.mkdir(parents=True, exist_ok=True)

        if not note_path.exists():
            note_path.write_text(
                build_new_vocabulary_note(row),
                encoding="utf-8",
            )

            created_count += 1
            print(f"[OK] Created vocabulary note: {note_path}")
            continue

        changed = update_existing_vocabulary_note(
            note_path=note_path,
            candidate=row,
        )

        if changed:
            updated_count += 1
            print(f"[OK] Updated vocabulary note: {note_path}")
        else:
            skipped_count += 1
            print(f"[SKIP] No change needed: {note_path}")

    return created_count, updated_count, skipped_count


def main() -> None:
    print("Build Vocabulary Atomic Notes")
    print("=" * 60)

    config = load_config()

    created_count, updated_count, skipped_count = build_vocabulary_atomic_notes(config)

    print("\nSummary")
    print("-" * 60)
    print(f"[OK] Created notes: {created_count}")
    print(f"[OK] Updated notes: {updated_count}")
    print(f"[SKIP] Skipped notes: {skipped_count}")


if __name__ == "__main__":
    main()
