from __future__ import annotations

import argparse

from languageos_tools.datastore.activity import get_activity_report, print_report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Show LanguageOS activity/review reports.",
    )

    parser.add_argument(
        "--view",
        required=True,
        choices=[
            "never-accessed",
            "least-accessed",
            "oldest-accessed",
            "recently-accessed",
            "high-seen-low-access",
            "stale-learning",
        ],
        help="Report view to show.",
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

    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of items.",
    )

    args = parser.parse_args()

    payload = get_activity_report(
        view=args.view,
        language=args.language,
        item_type=args.type,
        limit=args.limit,
    )

    print_report(payload)


if __name__ == "__main__":
    main()
