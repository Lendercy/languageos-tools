# LanguageOS Tools

Local-first automation tools for building a personal language learning operating system.

This repository contains the Python tooling for a local LanguageOS environment. The system indexes language-learning notes, transcripts, vocabulary, grammar, relations, writing errors, Anki candidates, and review metadata from a local Obsidian vault.

The project is designed around a simple rule:

```text
Obsidian notes are the source of truth.
SQLite is a rebuildable index.
JSON files are queues, exports, or debug artifacts.
```

## Current Status

This repository is currently in the `architecture-foundation-v1` phase.

The foundation includes:

* Core metadata models and frontmatter parsing
* Obsidian vault reader/writer layer
* Safe note writing with dry-run and backup support
* Relation taxonomy and relation validation service
* Migration framework for non-destructive note updates
* Schema version migration
* Human-readable relations template migration
* Relation backfill migration
* Structured relation parser
* SQLite relation repository
* Relation query CLI
* Language database rebuild CLI
* Search and lookup utilities

## Repository Layout

```text
languageos-tools/
├── configs/
│   └── languageos.config.json
├── scripts/
│   ├── build_language_db.py
│   ├── rebuild_relation_index.py
│   ├── query_relations.py
│   ├── migrate_schema_version.py
│   ├── migrate_relations_template.py
│   ├── migrate_relation_backfill.py
│   ├── audit_item_keys.py
│   ├── validate_schema.py
│   ├── run_daily_pipeline.py
│   └── ...
├── src/
│   └── languageos_tools/
│       ├── core/
│       ├── obsidian/
│       ├── datastore/
│       ├── relations/
│       ├── migrations/
│       ├── validation/
│       ├── search/
│       ├── vocabulary/
│       ├── writing/
│       ├── listening/
│       ├── anki/
│       ├── pipeline/
│       ├── tts/
│       └── ui/
├── pyproject.toml
└── README.md
```

## Local Folder Architecture

The code repository does not store the language-learning data itself.

Recommended local layout:

```text
D:\
├── Dev\
│   └── languageos-tools\
├── LanguageOS\
│   ├── Obsidian\
│   │   └── LanguageOS_vault\
│   ├── Inbox\
│   │   ├── Backups\
│   │   ├── Candidates\
│   │   └── Indexes\
│   │       └── languageos.db
│   └── ...
```

The default project paths used during development are:

```text
Code repository:
D:\Dev\languageos-tools

Obsidian vault:
D:\LanguageOS\Obsidian\LanguageOS_vault

SQLite index:
D:\LanguageOS\Inbox\Indexes\languageos.db
```

## Design Principles

LanguageOS follows these principles:

1. **Local-first**

   * Notes, indexes, and learning data live locally.
   * The system should remain usable without a cloud dependency.

2. **Obsidian as source of truth**

   * Markdown notes store the canonical learning data.
   * SQLite indexes can be rebuilt from notes.

3. **Non-destructive automation**

   * Scripts should avoid overwriting human-written content.
   * Migrations should support dry-run and backup.

4. **Typed, modular architecture**

   * Core logic lives under `src/languageos_tools`.
   * CLI scripts in `scripts/` are thin wrappers.

5. **Migration-first evolution**

   * Existing notes should be upgraded through migrations.
   * New schema changes should be versioned and idempotent.

6. **Human approval before learning-state changes**

   * AI may suggest, enrich, or rank.
   * AI should not automatically mark items as learned, delete notes, merge notes, or add Anki cards without approval.

## Main Concepts

### Language Item

A language item is a structured learning object represented by an Obsidian note.

Common item types include:

* `vocabulary`
* `sentence`
* `grammar`
* `transcript`
* `tts_audio`
* `writing_error`

Each note contains YAML frontmatter plus human-readable Markdown content.

### Item Key

Structured systems use an item key:

```text
type|language|normalized
```

Example:

```text
vocabulary|german|trotzdem
grammar|german|contrast connectors
sentence|german|trotzdem lerne ich deutsch
```

### Relations

Relations connect language items.

Examples:

```text
sentence --contains_vocabulary--> vocabulary
sentence --uses_grammar--> grammar
vocabulary --uses_grammar--> grammar
sentence --similar_to--> sentence
```

Relation types are controlled by:

```text
src/languageos_tools/relations/relation_types.json
```

This prevents uncontrolled relation naming and keeps the graph maintainable.

## Setup

From PowerShell:

```powershell
cd D:\Dev\languageos-tools

python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -e .
```

## Configuration

The main config file is:

```text
configs/languageos.config.json
```

It should point to the local LanguageOS root and Obsidian vault.

Example:

```json
{
  "languageos_root": "D:/LanguageOS",
  "obsidian_vault": "D:/LanguageOS/Obsidian/LanguageOS_vault",
  "outputs": {
    "languageos_db": "D:/LanguageOS/Inbox/Indexes/languageos.db"
  }
}
```

Do not commit secrets or private API keys.

## Common Commands

### Rebuild the SQLite language index

```powershell
python scripts\build_language_db.py
```

### Rebuild the structured relation index

```powershell
python scripts\rebuild_relation_index.py
```

### Query relations

```powershell
python scripts\query_relations.py "trotzdem"
python scripts\query_relations.py "Contrast connectors" --all
```

### Validate schema

```powershell
python scripts\validate_schema.py
```

### Run daily pipeline

```powershell
python scripts\run_daily_pipeline.py
```

## Migration Commands

### Add or verify note schema versions

```powershell
python scripts\migrate_schema_version.py --dry-run
python scripts\migrate_schema_version.py
```

### Add or upgrade the relations template

```powershell
python scripts\migrate_relations_template.py --dry-run
python scripts\migrate_relations_template.py
```

### Backfill generic relations from legacy sections

```powershell
python scripts\migrate_relation_backfill.py --dry-run
python scripts\migrate_relation_backfill.py
```

### Audit item key normalization

```powershell
python scripts\audit_item_keys.py
```

## Current Verified State

At the time of the architecture foundation checkpoint:

```text
Indexed items: 16
FTS documents: 16
Errors: 0

Types:
- grammar: 1
- transcript: 6
- sentence: 3
- tts_audio: 3
- vocabulary: 3

Languages:
- german: 14
- english: 2

Anki status:
- none: 15
- candidate: 1
```

The relation index successfully parses structured relations such as:

```text
sentence|german|trotzdem lerne ich deutsch --contains_vocabulary--> vocabulary|german|trotzdem
sentence|german|trotzdem lerne ich deutsch --uses_grammar--> grammar|german|contrast connectors
vocabulary|german|trotzdem --uses_grammar--> grammar|german|contrast connectors
```

## Development Workflow

Recommended workflow for every change:

```powershell
git status

# edit code

python scripts\build_language_db.py
python scripts\rebuild_relation_index.py

git status
git add .
git commit -m "Describe the change"
git status
```

For migrations:

```powershell
python scripts\<migration_script>.py --dry-run
python scripts\<migration_script>.py
python scripts\<migration_script>.py --dry-run
python scripts\build_language_db.py
python scripts\rebuild_relation_index.py
```

The second dry-run should ideally report zero updates.

## Roadmap

Near-term architecture tasks:

* Add item key normalization audit and migration
* Add tests for frontmatter parsing, normalization, relation parsing, and migrations
* Add centralized config loader
* Add CLI quality baseline
* Add GitHub Actions CI
* Improve README and developer documentation
* Add automatic relation enrichment with approval/dry-run
* Improve Anki candidate approval workflow
* Add semantic search and LLM-assisted suggestions

## License

Private personal project unless a license is explicitly added.
