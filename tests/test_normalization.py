from __future__ import annotations

from languageos_tools.core.normalization import (
    ItemKey,
    ItemKeyExtractor,
    ItemKeyNormalizer,
)


def test_item_key_normalizer_lowercases_and_removes_sentence_period() -> None:
    result = ItemKeyNormalizer().normalize_text(
        "Trotzdem lerne ich Deutsch.",
        item_type="sentence",
    )

    assert result.normalized == "trotzdem lerne ich deutsch"
    assert result.changed is True
    assert "casefold" in result.operations
    assert "strip_terminal_punctuation" in result.operations


def test_item_key_normalizer_collapses_whitespace() -> None:
    result = ItemKeyNormalizer().normalize_text(
        "  Ich   lerne   Deutsch  ",
        item_type="sentence",
    )

    assert result.normalized == "ich lerne deutsch"
    assert result.changed is True
    assert "trim" in result.operations
    assert "collapse_whitespace" in result.operations
    assert "casefold" in result.operations


def test_item_key_normalizer_keeps_german_umlauts() -> None:
    result = ItemKeyNormalizer().normalize_text(
        "Mädchen",
        item_type="vocabulary",
    )

    assert result.normalized == "mädchen"
    assert result.changed is True
    assert "casefold" in result.operations


def test_item_key_extractor_extracts_existing_normalized_frontmatter() -> None:
    item_key = ItemKeyExtractor().extract(
        {
            "type": "vocabulary",
            "language": "german",
            "normalized": "trotzdem",
        }
    )

    assert item_key is not None
    assert item_key.render() == "vocabulary|german|trotzdem"


def test_item_key_normalizer_normalizes_item_key_object() -> None:
    item_key = ItemKey(
        item_type="Sentence",
        language="German",
        normalized="Trotzdem lerne ich Deutsch.",
    )

    proposed, result = ItemKeyNormalizer().normalize_item_key(item_key)

    assert proposed.render() == "sentence|german|trotzdem lerne ich deutsch"
    assert result.normalized == "trotzdem lerne ich deutsch"