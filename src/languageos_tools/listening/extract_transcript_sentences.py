from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

CONFIG_PATH = Path("configs/languageos.config.json")


LANGUAGE_TO_FOLDER = {
    "english": "English",
    "german": "German",
}


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


def normalize_text(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[“”\"'`]", "", text)
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


def yaml_quote(value: str) -> str:
    value = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{value}"'


def infer_language_from_metadata(metadata: dict) -> str:
    for key in ["language", "language_setting", "detected_language"]:
        language = normalize_language(str(metadata.get(key) or ""))

        if language != "unknown":
            return language

    return "unknown"


def get_markdown_section(body: str, heading: str) -> str:
    """
    Extract content below a markdown heading until the next heading.

    Example:
    ## Raw Transcript
    text here

    ## Timestamped Transcript
    ...
    """
    pattern = rf"(?ims)^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)"
    match = re.search(pattern, body)

    if not match:
        return ""

    return match.group(1).strip()


def clean_transcript_text(text: str) -> str:
    text = re.sub(r"`?\[\d{2}:\d{2}:\d{2}\s*-\s*\d{2}:\d{2}:\d{2}\]`?", " ", text)
    text = re.sub(r"`?\[\d{2}:\d{2}\s*-\s*\d{2}:\d{2}\]`?", " ", text)

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
    """
    Simple multilingual sentence splitter.

    Good enough for v0.1:
    - German / English punctuation
    - keeps punctuation at the end
    """
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

        if re.fullmatch(r"[\W_]+", sentence):
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


def safe_filename_from_sentence(sentence: str, max_len: int = 80) -> str:
    name = sentence.strip()

    name = re.sub(r"[\\/:*?\"<>|]", " ", name)
    name = re.sub(r"\s+", " ", name)
    name = name.strip(" .")

    if not name:
        name = "Untitled Sentence"

    if len(name) > max_len:
        name = name[:max_len].rstrip()

    return f"{name}.md"


def get_existing_context_lines(body: str) -> list[str]:
    section = get_markdown_section(body, "Contexts")

    if not section:
        return []

    lines: list[str] = []

    for line in section.splitlines():
        stripped = line.strip()

        if stripped.startswith("- "):
            lines.append(stripped)

    return lines


def get_existing_notes_section(body: str) -> str:
    section = get_markdown_section(body, "Notes")
    return section.strip()


def build_sentence_note_content(
    sentence: str,
    language: str,
    metadata: dict,
    context_lines: list[str],
    existing_notes: str,
) -> str:
    today = datetime.now().date().isoformat()

    status = str(metadata.get("status") or "learning")
    anki_status = str(metadata.get("anki_status") or "none")
    level = str(metadata.get("level") or "unknown")
    difficulty = str(metadata.get("difficulty") or "unknown")
    confidence = str(metadata.get("confidence") or "medium")

    first_seen = str(metadata.get("first_seen") or today)
    last_seen = today

    seen_count = len(context_lines)

    normalized = normalize_text(sentence)

    topic_list = metadata.get("topic")

    if not isinstance(topic_list, list) or not topic_list:
        topic_list = ["daily_life"]

    skill_list = metadata.get("skill")

    if not isinstance(skill_list, list) or not skill_list:
        skill_list = ["listening", "speaking"]

    topic_yaml = "\n".join(f"  - {topic}" for topic in topic_list)
    skill_yaml = "\n".join(f"  - {skill}" for skill in skill_list)
    contexts_markdown = "\n".join(context_lines) if context_lines else "- "

    content = f"""---
type: sentence
language: {language}
sentence: {yaml_quote(sentence)}
normalized: {yaml_quote(normalized)}
status: {status}
anki_status: {anki_status}
topic:
{topic_yaml}
level: {level}
skill:
{skill_yaml}
source_type: stt
seen_count: {seen_count}
first_seen: {first_seen}
last_seen: {last_seen}
difficulty: {difficulty}
confidence: {confidence}
---

# {sentence}

🟡 Status: {status}  
📌 Anki: {anki_status}  
🔁 Seen: {seen_count}

## Sentence

{sentence}

## Meaning

TODO

## Contexts

{contexts_markdown}

## Related

- 

## Notes

{existing_notes}
"""

    return content


def process_transcript_note(
    vault_root: Path,
    transcript_path: Path,
    dry_run: bool,
) -> dict:
    text = transcript_path.read_text(encoding="utf-8")
    metadata, body, has_frontmatter = parse_frontmatter(text)

    if not has_frontmatter:
        return {
            "path": str(transcript_path),
            "status": "skipped",
            "reason": "missing frontmatter",
            "sentences": [],
        }

    note_type = str(metadata.get("type") or "").strip().lower()

    if note_type not in {"transcript", "listening_transcript"}:
        return {
            "path": str(transcript_path),
            "status": "skipped",
            "reason": f"not transcript type: {note_type}",
            "sentences": [],
        }

    language = infer_language_from_metadata(metadata)

    if language not in LANGUAGE_TO_FOLDER:
        return {
            "path": str(transcript_path),
            "status": "skipped",
            "reason": f"unsupported language: {language}",
            "sentences": [],
        }

    transcript_text = extract_transcript_text(body)
    sentences = split_sentences(transcript_text)

    sentence_folder = vault_root / "Sentences" / LANGUAGE_TO_FOLDER[language]
    sentence_folder.mkdir(parents=True, exist_ok=True)

    transcript_relative = transcript_path.relative_to(vault_root).as_posix()
    transcript_alias = str(metadata.get("source_file") or transcript_path.stem)
    transcript_link = f"[[{transcript_relative[:-3]}|{transcript_alias}]]"

    created = 0
    updated = 0
    unchanged = 0

    sentence_results: list[dict] = []

    for sentence in sentences:
        filename = safe_filename_from_sentence(sentence)
        sentence_path = sentence_folder / filename

        context_line = f"- {transcript_link} — {sentence}"

        existing_metadata: dict = {}
        existing_body = ""
        existing_context_lines: list[str] = []
        existing_notes = ""

        if sentence_path.exists():
            existing_text = sentence_path.read_text(encoding="utf-8")
            existing_metadata, existing_body, _ = parse_frontmatter(existing_text)
            existing_context_lines = get_existing_context_lines(existing_body)
            existing_notes = get_existing_notes_section(existing_body)

        context_keys = set(existing_context_lines)

        if context_line in context_keys:
            unchanged += 1
            action = "unchanged"
        else:
            existing_context_lines.append(context_line)

            if sentence_path.exists():
                updated += 1
                action = "updated"
            else:
                created += 1
                action = "created"

            if not dry_run:
                content = build_sentence_note_content(
                    sentence=sentence,
                    language=language,
                    metadata=existing_metadata,
                    context_lines=existing_context_lines,
                    existing_notes=existing_notes,
                )

                sentence_path.write_text(content, encoding="utf-8")

        sentence_results.append(
            {
                "sentence": sentence,
                "path": str(sentence_path),
                "action": action,
            }
        )

    return {
        "path": str(transcript_path),
        "status": "processed",
        "language": language,
        "sentence_count": len(sentences),
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "sentences": sentence_results,
    }


def find_transcript_notes(vault_root: Path) -> list[Path]:
    transcript_dir = vault_root / "Listening" / "Transcripts"

    if not transcript_dir.exists():
        return []

    return sorted(transcript_dir.rglob("*.md"))


def process_all_transcripts(dry_run: bool = False) -> dict:
    config = load_config()
    vault_root = Path(config["obsidian_vault"])

    if not vault_root.exists():
        raise FileNotFoundError(f"Obsidian vault not found: {vault_root}")

    transcript_notes = find_transcript_notes(vault_root)

    results: list[dict] = []

    totals = defaultdict(int)

    for transcript_path in transcript_notes:
        result = process_transcript_note(
            vault_root=vault_root,
            transcript_path=transcript_path,
            dry_run=dry_run,
        )

        results.append(result)

        if result["status"] == "processed":
            totals["processed"] += 1
            totals["sentences"] += int(result.get("sentence_count", 0))
            totals["created"] += int(result.get("created", 0))
            totals["updated"] += int(result.get("updated", 0))
            totals["unchanged"] += int(result.get("unchanged", 0))
        else:
            totals["skipped"] += 1

    return {
        "dry_run": dry_run,
        "transcript_notes": len(transcript_notes),
        "totals": dict(totals),
        "results": results,
    }


def print_summary(payload: dict) -> None:
    print("Extract Transcript Sentences")
    print("=" * 60)

    if payload["dry_run"]:
        print("[DRY RUN] No files were written.")

    print("\nSummary")
    print("-" * 60)
    print(f"[OK] Transcript notes found : {payload['transcript_notes']}")
    print(f"[OK] Processed transcript  : {payload['totals'].get('processed', 0)}")
    print(f"[SKIP] Skipped transcript  : {payload['totals'].get('skipped', 0)}")
    print(f"[OK] Sentences extracted   : {payload['totals'].get('sentences', 0)}")
    print(f"[OK] Sentence notes created: {payload['totals'].get('created', 0)}")
    print(f"[OK] Sentence notes updated: {payload['totals'].get('updated', 0)}")
    print(f"[OK] Sentence notes same   : {payload['totals'].get('unchanged', 0)}")

    print("\nDetails")
    print("-" * 60)

    for result in payload["results"]:
        path = result["path"]

        if result["status"] != "processed":
            print(f"[SKIP] {path} — {result.get('reason')}")
            continue

        print(
            f"[OK] {path} | "
            f"sentences={result.get('sentence_count', 0)} "
            f"created={result.get('created', 0)} "
            f"updated={result.get('updated', 0)} "
            f"same={result.get('unchanged', 0)}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract sentence notes from LanguageOS transcript notes.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview extraction without writing sentence notes.",
    )

    args = parser.parse_args()

    payload = process_all_transcripts(dry_run=args.dry_run)
    print_summary(payload)


if __name__ == "__main__":
    main()
