from __future__ import annotations

import argparse

from languageos_tools.datastore.activity import print_touch_result, touch_by_query


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Record access activity for a LanguageOS item.",
    )

    parser.add_argument(
        "query",
        help="Item text to touch, for example: trotzdem",
    )

    parser.add_argument(
        "--language",
        default=None,
        choices=["english", "german", "mixed", "unknown"],
        help="Optional language filter.",
    )

    parser.add_argument(
        "--type",
        default=None,
        choices=[
            "vocabulary",
            "sentence",
            "grammar",
            "transcript",
            "tts_audio",
            "writing_error",
        ],
        help="Optional item type filter.",
    )

    args = parser.parse_args()

    payload = touch_by_query(
        query=args.query,
        language=args.language,
        item_type=args.type,
    )

    print_touch_result(payload)


if __name__ == "__main__":
    main()
