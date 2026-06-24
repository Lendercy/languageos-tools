from __future__ import annotations

from languageos_tools.vocabulary.approve_vocabulary import main as approve_vocabulary
from languageos_tools.writing.approve_writing_errors import main as approve_writing_errors
from languageos_tools.anki.card_candidates import main as generate_anki_candidates
from languageos_tools.anki.approve_candidates import main as approve_anki_candidates
from languageos_tools.obsidian.sentence_bank import main as sync_sentence_bank_status
from languageos_tools.diagnostics.check_system import main as check_system


def main() -> None:
    print("LanguageOS Daily Pipeline")
    print("=" * 60)

    print("\n[1] Approve vocabulary candidates")
    print("-" * 60)
    approve_vocabulary()

    print("\n[2] Approve writing error candidates")
    print("-" * 60)
    approve_writing_errors()

    print("\n[3] Generate Anki candidates")
    print("-" * 60)
    generate_anki_candidates()

    print("\n[4] Approve Anki candidates")
    print("-" * 60)
    approve_anki_candidates()

    print("\n[5] Sync Sentence Bank Anki status")
    print("-" * 60)
    sync_sentence_bank_status()

    print("\n[6] Run system diagnostics")
    print("-" * 60)
    check_system()

    print("\nDaily Pipeline Summary")
    print("=" * 60)
    print("[OK] LanguageOS daily pipeline completed.")


if __name__ == "__main__":
    main()