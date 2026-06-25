from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizationResult:
    original: str
    normalized: str
    changed: bool
    reasons: tuple[str, ...]


class TextNormalizer:
    """
    Centralized text normalization for LanguageOS item keys.

    Design goals:
    - Stable item keys.
    - Language-agnostic enough for English/German.
    - Conservative: do not remove meaningful internal characters too aggressively.
    - Reusable by DB indexing, relation parsing, migrations, and future UI.
    """

    TRAILING_PUNCTUATION_PATTERN = re.compile(r"[.!?。！？]+$")
    MULTI_SPACE_PATTERN = re.compile(r"\s+")

    def normalize_key_text(self, text: str) -> NormalizationResult:
        original = str(text or "")
        value = original
        reasons: list[str] = []

        stripped = value.strip()
        if stripped != value:
            reasons.append("trimmed_outer_whitespace")
            value = stripped

        normalized_unicode = unicodedata.normalize("NFC", value)
        if normalized_unicode != value:
            reasons.append("unicode_nfc_normalized")
            value = normalized_unicode

        lower_value = value.lower()
        if lower_value != value:
            reasons.append("lowercased")
            value = lower_value

        compact_value = self.MULTI_SPACE_PATTERN.sub(" ", value)
        if compact_value != value:
            reasons.append("collapsed_whitespace")
            value = compact_value

        quote_cleaned = self._remove_quote_marks(value)
        if quote_cleaned != value:
            reasons.append("removed_quote_marks")
            value = quote_cleaned

        trailing_cleaned = self.TRAILING_PUNCTUATION_PATTERN.sub("", value).strip()
        if trailing_cleaned != value:
            reasons.append("removed_trailing_sentence_punctuation")
            value = trailing_cleaned

        return NormalizationResult(
            original=original,
            normalized=value,
            changed=original != value,
            reasons=tuple(reasons),
        )

    def _remove_quote_marks(self, text: str) -> str:
        return (
            text.replace("“", "")
            .replace("”", "")
            .replace('"', "")
            .replace("'", "")
            .replace("`", "")
        )


def normalize_key_text(text: str) -> str:
    return TextNormalizer().normalize_key_text(text).normalized