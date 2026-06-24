from __future__ import annotations

from enum import StrEnum


class ItemType(StrEnum):
    VOCABULARY = "vocabulary"
    SENTENCE = "sentence"
    GRAMMAR = "grammar"
    TRANSCRIPT = "transcript"
    LISTENING_TRANSCRIPT = "listening_transcript"
    TTS_AUDIO = "tts_audio"
    WRITING_ERROR = "writing_error"
    RESOURCE = "resource"
    UNKNOWN = "unknown"


class LanguageCode(StrEnum):
    ENGLISH = "english"
    GERMAN = "german"
    UNKNOWN = "unknown"


class LearningStatus(StrEnum):
    RAW_TRANSCRIPT = "raw_transcript"
    GENERATED = "generated"
    LEARNING = "learning"
    LEARNED = "learned"
    ARCHIVED = "archived"
    UNKNOWN = "unknown"


class AnkiStatus(StrEnum):
    NONE = "none"
    CANDIDATE = "candidate"
    ADDED = "added"
    REJECTED = "rejected"
    SUSPENDED = "suspended"
    UNKNOWN = "unknown"


class ReviewStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    ACTIVE = "active"
    STALE = "stale"
    REVIEWED = "reviewed"
    IGNORED = "ignored"
    UNKNOWN = "unknown"


class ReviewPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    UNKNOWN = "unknown"


class RelationType(StrEnum):
    CONTAINS_VOCABULARY = "contains_vocabulary"
    USES_GRAMMAR = "uses_grammar"
    EXAMPLE_OF = "example_of"
    SOURCE_OF = "source_of"
    DERIVED_FROM = "derived_from"

    SIMILAR_TO = "similar_to"
    OPPOSITE_OF = "opposite_of"
    CONTRAST_WITH = "contrast_with"
    CONFUSABLE_WITH = "confusable_with"
    NEGATIVE_COUNTERPART = "negative_counterpart"

    TRANSLATION_OF = "translation_of"
    TRANSLATION_VARIANT_OF = "translation_variant_of"

    FORMAL_VARIANT_OF = "formal_variant_of"
    INFORMAL_VARIANT_OF = "informal_variant_of"
    SLANG_VARIANT_OF = "slang_variant_of"
    REGISTER_VARIANT_OF = "register_variant_of"

    GRAMMAR_CONTRAST_WITH = "grammar_contrast_with"
    UNKNOWN = "unknown"


def normalize_enum_value(value: object, default: str = "unknown") -> str:
    if value is None:
        return default

    text = str(value).strip().lower()

    if not text:
        return default

    return text