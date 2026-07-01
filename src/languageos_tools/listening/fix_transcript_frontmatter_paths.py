from __future__ import annotations

import json
import re
from pathlib import Path

CONFIG_PATH = Path("configs/languageos.config.json")


PATH_KEYS = {
    "source_path",
    "audio_path",
    "video_path",
}


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalize_path_value(value: str) -> str:
    value = value.strip()

    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1]

    if value.startswith("'") and value.endswith("'"):
        value = value[1:-1]

    # Convert repeated Windows backslashes to forward slashes.
    value = re.sub(r"\\+", "/", value)

    # Clean excessive slashes in Windows drive paths.
    # Example:
    # D:////Dev////file.mp3 -> D:/Dev/file.mp3
    drive_match = re.match(r"^([A-Za-z]:)(/+)(.*)$", value)

    if drive_match:
        drive = drive_match.group(1)
        rest = drive_match.group(3)
        rest = re.sub(r"/+", "/", rest)
        value = f"{drive}/{rest}"
    else:
        value = re.sub(r"/+", "/", value)

    return value


def fix_frontmatter_paths(text: str) -> tuple[str, bool]:
    if not text.startswith("---"):
        return text, False

    parts = text.split("---", 2)

    if len(parts) < 3:
        return text, False

    frontmatter = parts[1].strip("\n")
    body = parts[2].lstrip("\n")

    changed = False
    fixed_lines: list[str] = []

    for line in frontmatter.splitlines():
        match = re.match(r"^(\s*)([A-Za-z0-9_]+)(\s*:\s*)(.*)$", line)

        if not match:
            fixed_lines.append(line)
            continue

        indent, key, sep, value = match.groups()

        if key not in PATH_KEYS:
            fixed_lines.append(line)
            continue

        fixed_value = normalize_path_value(value)

        if fixed_value != value.strip():
            changed = True

        fixed_lines.append(f"{indent}{key}{sep}{fixed_value}")

    if not changed:
        return text, False

    fixed_frontmatter = "\n".join(fixed_lines)
    fixed_text = f"---\n{fixed_frontmatter}\n---\n\n{body}"

    return fixed_text, True


def find_transcript_notes(vault_root: Path) -> list[Path]:
    transcript_dir = vault_root / "Listening" / "Transcripts"

    if not transcript_dir.exists():
        return []

    return sorted(transcript_dir.rglob("*.md"))


def main() -> None:
    config = load_config()
    vault_root = Path(config["obsidian_vault"])

    transcript_notes = find_transcript_notes(vault_root)

    fixed_count = 0
    unchanged_count = 0

    print("Fix Transcript Frontmatter Paths")
    print("=" * 60)

    for path in transcript_notes:
        text = path.read_text(encoding="utf-8")
        fixed_text, changed = fix_frontmatter_paths(text)

        if changed:
            path.write_text(fixed_text, encoding="utf-8")
            fixed_count += 1
            print(f"[FIX] {path}")
        else:
            unchanged_count += 1

    print("\nSummary")
    print("-" * 60)
    print(f"[OK] Transcript notes scanned: {len(transcript_notes)}")
    print(f"[OK] Fixed files             : {fixed_count}")
    print(f"[OK] Unchanged files         : {unchanged_count}")


if __name__ == "__main__":
    main()
