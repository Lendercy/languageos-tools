from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

CONFIG_PATH = Path("configs/languageos.config.json")


MANAGED_SECTIONS = [
    "Contains Vocabulary",
    "Grammar / Pattern",
]


@dataclass
class VocabularyItem:
    term: str
    language: str
    obsidian_path: str
    obsidian_link: str
    related_grammar_links: list[str]


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def parse_scalar_value(value: str):
    value = value.strip()

    if value in {"", "null", "None"}:
        return ""

    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]

    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]

    return value


def parse_frontmatter(text: str) -> tuple[dict, str, str, bool]:
    if not text.startswith("---"):
        return {}, "", text, False

    parts = text.split("---", 2)

    if len(parts) < 3:
        return {}, "", text, False

    raw_frontmatter = parts[1].strip("\n")
    body = parts[2].lstrip("\n")

    metadata: dict = {}
    current_list_key: str | None = None

    for raw_line in raw_frontmatter.splitlines():
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

    return metadata, raw_frontmatter, body, True


def normalize_text(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[“”\"'`]", "", text)
    text = re.sub(r"[.!?。！？]+$", "", text)
    return text.strip()


def safe_obsidian_path(vault_root: Path, note_path: Path) -> str:
    rel = note_path.relative_to(vault_root).as_posix()

    if rel.endswith(".md"):
        rel = rel[:-3]

    return rel


def build_obsidian_link(obsidian_path: str, display: str) -> str:
    return f"[[{obsidian_path}|{display}]]"


def get_markdown_section(body: str, heading: str) -> str:
    pattern = rf"(?ims)^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)"
    match = re.search(pattern, body)

    if not match:
        return ""

    return match.group(1).strip()


def remove_markdown_section(body: str, heading: str) -> str:
    pattern = rf"(?ims)\n*^##\s+{re.escape(heading)}\s*$\n.*?(?=^##\s+|\Z)"
    return re.sub(pattern, "", body).rstrip()


def extract_wikilinks(text: str) -> list[str]:
    links: list[str] = []

    for match in re.finditer(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", text):
        target = match.group(1).strip()
        display = match.group(2).strip() if match.group(2) else target.split("/")[-1]
        links.append(build_obsidian_link(target, display))

    return unique_keep_order(links)


def link_key(link: str) -> str:
    match = re.match(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", link)

    if not match:
        return link.strip().lower()

    return match.group(1).strip().lower()


def unique_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []

    for value in values:
        key = link_key(value)

        if key in seen:
            continue

        seen.add(key)
        result.append(value)

    return result


def term_matches_sentence(term: str, sentence: str) -> bool:
    term_norm = normalize_text(term)
    sentence_norm = normalize_text(sentence)

    if not term_norm or not sentence_norm:
        return False

    if len(term_norm) < 3:
        return False

    # Multi-word phrase: simple containment is usually safer.
    if " " in term_norm:
        return term_norm in sentence_norm

    # Single word: avoid matching inside longer words.
    boundary_chars = r"A-Za-z0-9_ÄÖÜäöüß"
    pattern = rf"(?<![{boundary_chars}]){re.escape(term_norm)}(?![{boundary_chars}])"

    return re.search(pattern, sentence_norm, flags=re.IGNORECASE) is not None


def find_markdown_notes(root: Path) -> list[Path]:
    if not root.exists():
        return []

    return sorted(root.rglob("*.md"))


def load_vocabulary_items(vault_root: Path) -> list[VocabularyItem]:
    vocab_root = vault_root / "Vocabulary"
    vocab_items: list[VocabularyItem] = []

    for note_path in find_markdown_notes(vocab_root):
        text = note_path.read_text(encoding="utf-8")
        metadata, _raw_frontmatter, body, has_frontmatter = parse_frontmatter(text)

        if not has_frontmatter:
            continue

        note_type = str(metadata.get("type") or "").strip().lower()

        if note_type != "vocabulary":
            continue

        language = str(metadata.get("language") or "unknown").strip().lower()
        term = str(metadata.get("term") or note_path.stem).strip()

        if not term:
            continue

        obsidian_path = safe_obsidian_path(vault_root, note_path)
        obsidian_link = build_obsidian_link(obsidian_path, term)

        related_grammar_text = get_markdown_section(body, "Related Grammar")
        related_grammar_links = extract_wikilinks(related_grammar_text)

        vocab_items.append(
            VocabularyItem(
                term=term,
                language=language,
                obsidian_path=obsidian_path,
                obsidian_link=obsidian_link,
                related_grammar_links=related_grammar_links,
            )
        )

    return vocab_items


def get_sentence_text(metadata: dict, body: str, note_path: Path) -> str:
    sentence = str(metadata.get("sentence") or "").strip()

    if sentence:
        return sentence

    section_sentence = get_markdown_section(body, "Sentence").strip()

    if section_sentence:
        return section_sentence.splitlines()[0].strip()

    return note_path.stem.strip()


def build_section(heading: str, links: list[str]) -> str:
    if not links:
        return ""

    lines = [f"## {heading}", ""]

    for link in links:
        lines.append(f"- {link}")

    return "\n".join(lines).strip()


def enrich_sentence_note(
    note_path: Path,
    vault_root: Path,
    vocab_items: list[VocabularyItem],
    dry_run: bool,
) -> dict:
    text = note_path.read_text(encoding="utf-8")
    metadata, raw_frontmatter, body, has_frontmatter = parse_frontmatter(text)

    if not has_frontmatter:
        return {
            "path": str(note_path),
            "status": "skipped",
            "reason": "missing frontmatter",
        }

    note_type = str(metadata.get("type") or "").strip().lower()

    if note_type != "sentence":
        return {
            "path": str(note_path),
            "status": "skipped",
            "reason": f"not sentence type: {note_type}",
        }

    language = str(metadata.get("language") or "unknown").strip().lower()
    sentence = get_sentence_text(metadata, body, note_path)

    detected_vocab_links: list[str] = []
    detected_grammar_links: list[str] = []

    for vocab in vocab_items:
        if vocab.language != language:
            continue

        if term_matches_sentence(vocab.term, sentence):
            detected_vocab_links.append(vocab.obsidian_link)
            detected_grammar_links.extend(vocab.related_grammar_links)

    existing_vocab_links = extract_wikilinks(
        get_markdown_section(body, "Contains Vocabulary")
    )
    existing_grammar_links = extract_wikilinks(
        get_markdown_section(body, "Grammar / Pattern")
    )

    final_vocab_links = unique_keep_order(detected_vocab_links + existing_vocab_links)
    final_grammar_links = unique_keep_order(
        detected_grammar_links + existing_grammar_links
    )

    if not final_vocab_links and not final_grammar_links:
        return {
            "path": str(note_path),
            "status": "unchanged",
            "sentence": sentence,
            "reason": "no vocabulary/grammar links detected",
        }

    new_body = body

    for section in MANAGED_SECTIONS:
        new_body = remove_markdown_section(new_body, section)

    managed_blocks = []

    vocab_section = build_section("Contains Vocabulary", final_vocab_links)
    grammar_section = build_section("Grammar / Pattern", final_grammar_links)

    if vocab_section:
        managed_blocks.append(vocab_section)

    if grammar_section:
        managed_blocks.append(grammar_section)

    new_body = new_body.rstrip() + "\n\n" + "\n\n".join(managed_blocks) + "\n"
    new_text = f"---\n{raw_frontmatter}\n---\n\n{new_body}"

    if new_text == text:
        return {
            "path": str(note_path),
            "status": "unchanged",
            "sentence": sentence,
            "vocabulary_links": final_vocab_links,
            "grammar_links": final_grammar_links,
        }

    if not dry_run:
        note_path.write_text(new_text, encoding="utf-8")

    return {
        "path": str(note_path),
        "status": "would_update" if dry_run else "updated",
        "sentence": sentence,
        "vocabulary_links": final_vocab_links,
        "grammar_links": final_grammar_links,
    }


def backup_sentence_notes(vault_root: Path, backup_root: Path) -> int:
    sentence_root = vault_root / "Sentences"

    if not sentence_root.exists():
        return 0

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = backup_root / f"sentence-link-enrichment.{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    count = 0

    for note_path in sentence_root.rglob("*.md"):
        rel = note_path.relative_to(sentence_root)
        backup_path = backup_dir / rel
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_text(note_path.read_text(encoding="utf-8"), encoding="utf-8")
        count += 1

    return count


def enrich_sentence_links(dry_run: bool, backup: bool) -> dict:
    config = load_config()
    vault_root = Path(config["obsidian_vault"])
    backup_root = (
        Path(config["languageos_root"]) / "Inbox" / "Backups" / "SentenceLinkEnrichment"
    )

    vocab_items = load_vocabulary_items(vault_root)
    sentence_root = vault_root / "Sentences"
    sentence_notes = find_markdown_notes(sentence_root)

    backup_count = 0

    if backup and not dry_run:
        backup_count = backup_sentence_notes(vault_root, backup_root)

    totals = {
        "sentence_notes": len(sentence_notes),
        "vocabulary_items": len(vocab_items),
        "updated": 0,
        "unchanged": 0,
        "skipped": 0,
        "errors": 0,
    }

    results: list[dict] = []

    for note_path in sentence_notes:
        try:
            result = enrich_sentence_note(
                note_path=note_path,
                vault_root=vault_root,
                vocab_items=vocab_items,
                dry_run=dry_run,
            )

            results.append(result)

            status = result["status"]

            if status in {"updated", "would_update"}:
                totals["updated"] += 1
            elif status == "unchanged":
                totals["unchanged"] += 1
            elif status == "skipped":
                totals["skipped"] += 1

        except Exception as exc:
            totals["errors"] += 1
            results.append(
                {
                    "path": str(note_path),
                    "status": "error",
                    "reason": str(exc),
                }
            )

    return {
        "dry_run": dry_run,
        "backup": backup,
        "backup_count": backup_count,
        "vault_root": str(vault_root),
        "totals": totals,
        "results": results,
    }


def print_summary(payload: dict) -> None:
    print("Enrich Sentence Links")
    print("=" * 60)

    if payload["dry_run"]:
        print("[DRY RUN] No notes were changed.")

    print(f"Vault  : {payload['vault_root']}")
    print(f"Backup : {payload['backup']}")

    if payload["backup_count"]:
        print(f"[OK] Backed up sentence notes: {payload['backup_count']}")

    print("\nSummary")
    print("-" * 60)

    totals = payload["totals"]

    print(f"[OK] Sentence notes   : {totals['sentence_notes']}")
    print(f"[OK] Vocabulary items : {totals['vocabulary_items']}")
    print(f"[OK] Updated          : {totals['updated']}")
    print(f"[OK] Unchanged        : {totals['unchanged']}")
    print(f"[SKIP] Skipped        : {totals['skipped']}")
    print(f"[ERROR] Errors        : {totals['errors']}")

    print("\nDetails")
    print("-" * 60)

    for result in payload["results"]:
        status = result["status"]
        path = result["path"]

        if status in {"updated", "would_update"}:
            print(f"[{status.upper()}] {result.get('sentence')}")
            print(f"  path: {path}")

            vocab_links = result.get("vocabulary_links") or []
            grammar_links = result.get("grammar_links") or []

            if vocab_links:
                print(f"  vocabulary: {', '.join(vocab_links)}")

            if grammar_links:
                print(f"  grammar   : {', '.join(grammar_links)}")

        elif status == "unchanged":
            print(
                f"[OK] {result.get('sentence', path)} — {result.get('reason', 'unchanged')}"
            )
        elif status == "skipped":
            print(f"[SKIP] {path} — {result.get('reason')}")
        elif status == "error":
            print(f"[ERROR] {path} — {result.get('reason')}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich sentence notes with vocabulary and grammar links.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing notes.",
    )

    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not back up sentence notes before writing.",
    )

    args = parser.parse_args()

    payload = enrich_sentence_links(
        dry_run=args.dry_run,
        backup=not args.no_backup,
    )

    print_summary(payload)


if __name__ == "__main__":
    main()
