from __future__ import annotations

from languageos_tools.core.frontmatter import FrontmatterParser


def test_parse_frontmatter_with_body() -> None:
    text = """---
type: vocabulary
language: german
term: trotzdem
tags:
  - lang/german
  - los/vocabulary
---

## Meaning

nevertheless
"""

    document = FrontmatterParser().parse(text)

    assert document.has_frontmatter is True
    assert document.get_str("type") == "vocabulary"
    assert document.get_str("language") == "german"
    assert document.get_str("term") == "trotzdem"
    assert "## Meaning" in document.body


def test_render_roundtrip_preserves_basic_metadata() -> None:
    parser = FrontmatterParser()

    text = """---
type: sentence
language: german
sentence: Trotzdem lerne ich Deutsch.
---

## Meaning

Nevertheless, I am learning German.
"""

    document = parser.parse(text)
    rendered = parser.render(document)
    reparsed = parser.parse(rendered)

    assert reparsed.has_frontmatter is True
    assert reparsed.get_str("type") == "sentence"
    assert reparsed.get_str("language") == "german"
    assert reparsed.get_str("sentence") == "Trotzdem lerne ich Deutsch."
    assert "Nevertheless" in reparsed.body


def test_parse_without_frontmatter() -> None:
    text = "Just plain markdown."

    document = FrontmatterParser().parse(text)

    assert document.has_frontmatter is False
    assert document.metadata == {}
    assert document.body == text
