from __future__ import annotations

from pathlib import Path

from languageos_tools.obsidian.note import VaultNote
from languageos_tools.relations.parser import (
    RelationMarkdownParser,
    build_relation_parse_context,
)
from languageos_tools.relations.service import RelationService
from languageos_tools.relations.taxonomy import RelationTaxonomy


def make_note(relative_path: str, text: str) -> VaultNote:
    vault_root = Path("D:/fake/vault")

    return VaultNote(
        vault_root=vault_root,
        absolute_path=vault_root / f"{relative_path}.md",
        text=text,
    )


def make_parser() -> RelationMarkdownParser:
    taxonomy = RelationTaxonomy.load(
        Path("src/languageos_tools/relations/relation_types.json")
    )
    service = RelationService(taxonomy)
    return RelationMarkdownParser(service)


def test_relation_parser_parses_generic_relations_section() -> None:
    sentence_note = make_note(
        "Sentences/German/Trotzdem lerne ich Deutsch",
        """---
type: sentence
language: german
sentence: Trotzdem lerne ich Deutsch.
normalized: trotzdem lerne ich deutsch
---

## Relations

### Contains Vocabulary

relation_type: `contains_vocabulary`

- [[Vocabulary/German/trotzdem|trotzdem]]
""",
    )

    vocab_note = make_note(
        "Vocabulary/German/trotzdem",
        """---
type: vocabulary
language: german
term: trotzdem
normalized: trotzdem
---

## Meaning

nevertheless
""",
    )

    notes = [sentence_note, vocab_note]
    context = build_relation_parse_context(notes)

    relations = make_parser().parse_note(sentence_note, context)

    assert len(relations) == 1
    assert relations[0].relation_type.value == "contains_vocabulary"
    assert relations[0].source_key.as_string() == (
        "sentence|german|trotzdem lerne ich deutsch"
    )
    assert relations[0].target_key.as_string() == "vocabulary|german|trotzdem"


def test_relation_parser_ignores_todo_links() -> None:
    sentence_note = make_note(
        "Sentences/German/TODO Example",
        """---
type: sentence
language: german
sentence: TODO Example.
normalized: todo example
---

## Relations

### Contains Vocabulary

relation_type: `contains_vocabulary`

- TODO
""",
    )

    context = build_relation_parse_context([sentence_note])

    relations = make_parser().parse_note(sentence_note, context)

    assert relations == []


def test_relation_parser_parses_legacy_related_grammar_section() -> None:
    vocab_note = make_note(
        "Vocabulary/German/trotzdem",
        """---
type: vocabulary
language: german
term: trotzdem
normalized: trotzdem
---

## Related Grammar

- [[Grammar/German/Contrast connectors|Contrast connectors]]
""",
    )

    grammar_note = make_note(
        "Grammar/German/Contrast connectors",
        """---
type: grammar
language: german
title: Contrast connectors
normalized: contrast connectors
---

## Pattern

aber, trotzdem, obwohl
""",
    )

    notes = [vocab_note, grammar_note]
    context = build_relation_parse_context(notes)

    relations = make_parser().parse_note(vocab_note, context)

    assert len(relations) == 1
    assert relations[0].relation_type.value == "uses_grammar"
    assert relations[0].source_key.as_string() == "vocabulary|german|trotzdem"
    assert relations[0].target_key.as_string() == ("grammar|german|contrast connectors")
