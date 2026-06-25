from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from languageos_tools.core.frontmatter import FrontmatterParser
from languageos_tools.core.normalization import TextNormalizer
from languageos_tools.obsidian.vault import ObsidianVault


CONFIG_PATH = Path("configs/languageos.config.json")


@dataclass(frozen=True)
class KeyAuditIssue:
    path: Path
    item_type: str
    language: str
    title: str
    current_normalized: str
    expected_normalized: str
    reasons: tuple[str, ...]

    @property
    def current_key(self) -> str:
        return f"{self.item_type}|{self.language}|{self.current_normalized}"

    @property
    def expected_key(self) -> str:
        return f"{self.item_type}|{self.language}|{self.expected_normalized}"


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")

    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def derive_source_text(metadata: dict[str, Any], note_title: str) -> str:
    for key in ("normalized", "term", "sentence", "title"):
        value = str(metadata.get(key) or "").strip()

        if value:
            return value

    return note_title


def audit_item_keys(vault_root: Path) -> list[KeyAuditIssue]:
    vault = ObsidianVault(vault_root)
    parser = FrontmatterParser()
    normalizer = TextNormalizer()

    issues: list[KeyAuditIssue] = []

    for note in vault.iter_notes():
        document = note.parse(parser)

        if not document.has_frontmatter:
            continue

        item_type = document.get_str("type").strip().lower()

        if not item_type:
            continue

        language = document.get_str("language", "unknown").strip().lower()
        current_normalized = document.get_str("normalized").strip().lower()
        source_text = derive_source_text(document.metadata, note.title)

        expected = normalizer.normalize_key_text(source_text)

        if not current_normalized:
            current_normalized = normalizer.normalize_key_text(source_text).normalized

        if current_normalized != expected.normalized:
            issues.append(
                KeyAuditIssue(
                    path=note.absolute_path,
                    item_type=item_type,
                    language=language or "unknown",
                    title=note.title,
                    current_normalized=current_normalized,
                    expected_normalized=expected.normalized,
                    reasons=expected.reasons,
                )
            )

    return issues


def print_report(issues: list[KeyAuditIssue]) -> None:
    print("LanguageOS Item Key Audit")
    print("=" * 60)
    print(f"[OK] Issues found: {len(issues)}")

    if not issues:
        print("\nNo key normalization issues found.")
        return

    print("\nIssues")
    print("-" * 60)

    for idx, issue in enumerate(issues, start=1):
        print(f"[ISSUE #{idx}] {issue.title}")
        print(f"  path     : {issue.path}")
        print(f"  type     : {issue.item_type}")
        print(f"  language : {issue.language}")
        print(f"  current  : {issue.current_key}")
        print(f"  expected : {issue.expected_key}")

        if issue.reasons:
            print(f"  reasons  : {', '.join(issue.reasons)}")

        print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit LanguageOS note normalized keys without modifying files.",
    )
    parser.add_argument(
        "--fail-on-issues",
        action="store_true",
        help="Exit with code 1 when key issues are found.",
    )

    args = parser.parse_args()

    config = load_config()
    vault_root = Path(config["obsidian_vault"])

    issues = audit_item_keys(vault_root)
    print_report(issues)

    if args.fail_on_issues and issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()