from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from languageos_tools.core.normalization import (
    NormalizationConfig,
    NormalizationProfile,
)


class KeyPolicyError(RuntimeError):
    """Raised when key policy registry config is invalid."""


@dataclass(frozen=True)
class KeyPolicyRule:
    lowercase: bool
    trim: bool
    collapse_whitespace: bool
    strip_terminal_punctuation: bool
    terminal_punctuation_pattern: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> KeyPolicyRule:
        return cls(
            lowercase=bool(data.get("lowercase", True)),
            trim=bool(data.get("trim", True)),
            collapse_whitespace=bool(data.get("collapse_whitespace", True)),
            strip_terminal_punctuation=bool(
                data.get("strip_terminal_punctuation", False)
            ),
            terminal_punctuation_pattern=str(
                data.get("terminal_punctuation_pattern", r"[.!?。！？]+$")
            ),
        )

    def merge(self, override: Mapping[str, Any]) -> KeyPolicyRule:
        data = {
            "lowercase": self.lowercase,
            "trim": self.trim,
            "collapse_whitespace": self.collapse_whitespace,
            "strip_terminal_punctuation": self.strip_terminal_punctuation,
            "terminal_punctuation_pattern": self.terminal_punctuation_pattern,
        }
        data.update(dict(override))
        return KeyPolicyRule.from_mapping(data)


@dataclass(frozen=True)
class KeyPolicyProfile:
    name: str
    description: str
    unicode_form: str
    default_rule: KeyPolicyRule
    item_type_rules: Mapping[str, KeyPolicyRule]

    def rule_for_item_type(self, item_type: str) -> KeyPolicyRule:
        normalized_item_type = item_type.strip().casefold()
        return self.item_type_rules.get(normalized_item_type, self.default_rule)

    def terminal_punctuation_item_types(self) -> frozenset[str]:
        return frozenset(
            item_type
            for item_type, rule in self.item_type_rules.items()
            if rule.strip_terminal_punctuation
        )

    def to_normalization_config(self) -> NormalizationConfig:
        """
        Bridge the registry to the existing ItemKeyNormalizer.

        The current NormalizationConfig supports a shared base config plus a set
        of item types that strip terminal punctuation. This keeps the migration
        non-breaking while moving the policy source into config.
        """
        return NormalizationConfig(
            profile=NormalizationProfile.KEY_V1,
            lowercase=self.default_rule.lowercase,
            unicode_form=self.unicode_form,
            collapse_whitespace=self.default_rule.collapse_whitespace,
            trim=self.default_rule.trim,
            strip_terminal_punctuation_item_types=self.terminal_punctuation_item_types(),
            terminal_punctuation_pattern=self.default_rule.terminal_punctuation_pattern,
        )


@dataclass(frozen=True)
class KeyPolicyRegistry:
    schema_version: str
    default_profile: str
    profiles: Mapping[str, KeyPolicyProfile]

    EXPECTED_SCHEMA_VERSION = "key_policy_registry_v1"

    @classmethod
    def load(cls, path: Path) -> KeyPolicyRegistry:
        if not path.exists():
            raise FileNotFoundError(f"Key policy registry does not exist: {path}")

        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_mapping(data)

    @classmethod
    def load_default(cls) -> KeyPolicyRegistry:
        project_root = Path(__file__).resolve().parents[3]
        return cls.load(project_root / "configs" / "key_policies.json")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> KeyPolicyRegistry:
        schema_version = str(data.get("schema_version", "")).strip()
        if schema_version != cls.EXPECTED_SCHEMA_VERSION:
            raise KeyPolicyError(
                f"Unsupported key policy schema_version: {schema_version!r}. "
                f"Expected: {cls.EXPECTED_SCHEMA_VERSION!r}"
            )

        default_profile = str(data.get("default_profile", "")).strip()
        raw_profiles = data.get("profiles")

        if not default_profile:
            raise KeyPolicyError("Missing default_profile in key policy registry.")

        if not isinstance(raw_profiles, dict) or not raw_profiles:
            raise KeyPolicyError("Missing or empty profiles in key policy registry.")

        profiles: dict[str, KeyPolicyProfile] = {}

        for profile_name, raw_profile in raw_profiles.items():
            if not isinstance(raw_profile, dict):
                raise KeyPolicyError(f"Invalid profile config for {profile_name!r}.")

            profiles[str(profile_name)] = cls._parse_profile(
                name=str(profile_name),
                data=raw_profile,
            )

        if default_profile not in profiles:
            raise KeyPolicyError(
                f"default_profile {default_profile!r} does not exist in profiles."
            )

        return cls(
            schema_version=schema_version,
            default_profile=default_profile,
            profiles=profiles,
        )

    @classmethod
    def _parse_profile(
        cls,
        *,
        name: str,
        data: Mapping[str, Any],
    ) -> KeyPolicyProfile:
        raw_default_rules = data.get("default_rules")
        if not isinstance(raw_default_rules, dict):
            raise KeyPolicyError(f"Profile {name!r} missing default_rules.")

        default_rule = KeyPolicyRule.from_mapping(raw_default_rules)

        raw_overrides = data.get("item_type_overrides", {})
        if not isinstance(raw_overrides, dict):
            raise KeyPolicyError(
                f"Profile {name!r} item_type_overrides must be an object."
            )

        item_type_rules: dict[str, KeyPolicyRule] = {}
        for item_type, raw_override in raw_overrides.items():
            if not isinstance(raw_override, dict):
                raise KeyPolicyError(
                    f"Invalid override for item_type {item_type!r} in profile {name!r}."
                )

            normalized_item_type = str(item_type).strip().casefold()
            if not normalized_item_type:
                raise KeyPolicyError(f"Empty item_type override in profile {name!r}.")

            item_type_rules[normalized_item_type] = default_rule.merge(raw_override)

        return KeyPolicyProfile(
            name=name,
            description=str(data.get("description", "")),
            unicode_form=str(data.get("unicode_form", "NFKC")),
            default_rule=default_rule,
            item_type_rules=item_type_rules,
        )

    def get_profile(self, name: str | None = None) -> KeyPolicyProfile:
        profile_name = name or self.default_profile

        try:
            return self.profiles[profile_name]
        except KeyError as exc:
            raise KeyPolicyError(
                f"Unknown key policy profile: {profile_name!r}"
            ) from exc

    def to_normalization_config(
        self, profile_name: str | None = None
    ) -> NormalizationConfig:
        return self.get_profile(profile_name).to_normalization_config()
