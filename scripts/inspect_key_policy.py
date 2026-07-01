from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from languageos_tools.core.key_policy import KeyPolicyRegistry


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect LanguageOS key policy registry.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs" / "key_policies.json",
        help="Path to key policy registry JSON.",
    )
    parser.add_argument(
        "--profile",
        type=str,
        default=None,
        help="Profile name. Defaults to registry default_profile.",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    registry = KeyPolicyRegistry.load(args.config)
    profile = registry.get_profile(args.profile)

    print("Key Policy Registry")
    print("=" * 80)
    print(f"Schema version : {registry.schema_version}")
    print(f"Default profile: {registry.default_profile}")
    print(f"Active profile : {profile.name}")
    print(f"Description    : {profile.description}")
    print(f"Unicode form   : {profile.unicode_form}")
    print("-" * 80)

    print("Default rule")
    print(f"  lowercase                   : {profile.default_rule.lowercase}")
    print(f"  trim                        : {profile.default_rule.trim}")
    print(f"  collapse_whitespace         : {profile.default_rule.collapse_whitespace}")
    print(
        "  strip_terminal_punctuation  : "
        f"{profile.default_rule.strip_terminal_punctuation}"
    )
    print(
        "  terminal_punctuation_pattern: "
        f"{profile.default_rule.terminal_punctuation_pattern}"
    )

    print("-" * 80)
    print("Item type rules")
    for item_type in sorted(profile.item_type_rules):
        rule = profile.item_type_rules[item_type]
        print(f"- {item_type}")
        print(f"    lowercase                  : {rule.lowercase}")
        print(f"    trim                       : {rule.trim}")
        print(f"    collapse_whitespace        : {rule.collapse_whitespace}")
        print(f"    strip_terminal_punctuation : {rule.strip_terminal_punctuation}")

    config = profile.to_normalization_config()
    print("-" * 80)
    print("Derived NormalizationConfig")
    print(f"  profile                             : {config.profile.value}")
    print(
        "  strip_terminal_punctuation_item_types: "
        f"{sorted(config.strip_terminal_punctuation_item_types)}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
