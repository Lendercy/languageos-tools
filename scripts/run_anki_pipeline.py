from __future__ import annotations

from languageos_tools.anki.approve_candidates import main as approve_candidates
from languageos_tools.anki.card_candidates import main as generate_candidates
from languageos_tools.obsidian.sentence_bank import main as sync_sentence_bank_status


def main() -> None:
    print("LanguageOS Anki Pipeline")
    print("=" * 60)

    print("\n[1] Generate Anki candidates")
    print("-" * 60)
    generate_candidates()

    print("\n[2] Approve Anki candidates")
    print("-" * 60)
    approve_candidates()

    print("\n[3] Sync Sentence Bank Anki status")
    print("-" * 60)
    sync_sentence_bank_status()

    print("\nPipeline Summary")
    print("=" * 60)
    print("[OK] Anki pipeline completed.")


if __name__ == "__main__":
    main()
