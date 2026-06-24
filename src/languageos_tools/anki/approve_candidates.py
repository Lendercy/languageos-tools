from __future__ import annotations

import json
from pathlib import Path

import requests


CONFIG_PATH = Path("configs/languageos.config.json")


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_candidates(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Candidate file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_candidates(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def anki_request(url: str, action: str, params: dict | None = None) -> dict:
    payload = {
        "action": action,
        "version": 6,
    }

    if params is not None:
        payload["params"] = params

    response = requests.post(url, json=payload, timeout=10)
    response.raise_for_status()

    data = response.json()

    if data.get("error") is not None:
        raise RuntimeError(f"AnkiConnect error: {data['error']}")

    return data


def get_deck_name(config: dict, candidate: dict) -> str:
    language = candidate.get("language", "english").lower()
    decks = config.get("anki", {}).get("decks", {})

    if language == "german":
        return decks.get("german", "LanguageOS::German")

    return decks.get("english", "LanguageOS::English")


def get_model_name(config: dict) -> str:
    return config.get("anki", {}).get("model_name", "Basic")


def ensure_deck_exists(anki_url: str, deck_name: str) -> None:
    anki_request(
        url=anki_url,
        action="createDeck",
        params={"deck": deck_name},
    )


def escape_anki_query_text(text: str) -> str:
    """
    Escape quotes for Anki browser search query.
    """
    return text.replace('"', '\\"')


def find_existing_notes_by_front(anki_url: str, deck_name: str, front: str) -> list[int]:
    """
    Try to find existing notes with the same Front text in the target deck.

    This is a pre-check. AnkiConnect's addNote duplicate protection is still
    the final safety layer.
    """
    escaped_front = escape_anki_query_text(front)
    escaped_deck = escape_anki_query_text(deck_name)

    query = f'deck:"{escaped_deck}" Front:"{escaped_front}"'

    result = anki_request(
        url=anki_url,
        action="findNotes",
        params={"query": query},
    )

    note_ids = result.get("result", [])
    return note_ids if isinstance(note_ids, list) else []


def build_anki_note(config: dict, candidate: dict) -> dict:
    deck_name = get_deck_name(config, candidate)
    model_name = get_model_name(config)

    front = candidate["front"]
    back = candidate["back"]
    tags = candidate.get("tags", [])

    return {
        "deckName": deck_name,
        "modelName": model_name,
        "fields": {
            "Front": front,
            "Back": back,
        },
        "tags": tags,
        "options": {
            "allowDuplicate": False,
            "duplicateScope": "deck",
        },
    }


def mark_candidate_as_duplicate(
    candidate: dict,
    deck_name: str,
    reason: str,
    existing_note_ids: list[int] | None = None,
) -> None:
    candidate["status"] = "duplicate"
    candidate["anki_deck"] = deck_name
    candidate["duplicate_reason"] = reason

    if existing_note_ids:
        candidate["existing_anki_note_ids"] = existing_note_ids


def approve_pending_candidates(config: dict, payload: dict) -> int:
    anki_url = config["external_tools"]["anki_connect_url"]

    approved_count = 0
    duplicate_count = 0
    error_count = 0

    for candidate in payload.get("candidates", []):
        if candidate.get("status") != "pending_review":
            continue

        note = build_anki_note(config, candidate)
        deck_name = note["deckName"]
        front = candidate["front"]

        try:
            ensure_deck_exists(anki_url, deck_name)

            existing_note_ids = find_existing_notes_by_front(
                anki_url=anki_url,
                deck_name=deck_name,
                front=front,
            )

            if existing_note_ids:
                mark_candidate_as_duplicate(
                    candidate=candidate,
                    deck_name=deck_name,
                    reason="Existing note found before addNote.",
                    existing_note_ids=existing_note_ids,
                )
                duplicate_count += 1

                print(f"[SKIP] Duplicate in {deck_name}: {front}")
                continue

            result = anki_request(
                url=anki_url,
                action="addNote",
                params={"note": note},
            )

            candidate["status"] = "approved"
            candidate["anki_note_id"] = result.get("result")
            candidate["anki_deck"] = deck_name
            approved_count += 1

            print(f"[OK] Added card to {deck_name}: {front}")

        except Exception as exc:
            error_text = str(exc)

            if "duplicate" in error_text.lower():
                mark_candidate_as_duplicate(
                    candidate=candidate,
                    deck_name=deck_name,
                    reason=error_text,
                )
                duplicate_count += 1

                print(f"[SKIP] Duplicate in {deck_name}: {front}")
                continue

            candidate["status"] = "error"
            candidate["error"] = error_text
            error_count += 1

            print(f"[ERROR] Failed to add card: {front}")
            print(f"        {error_text}")

    print("\nDetailed Result")
    print("-" * 60)
    print(f"[OK] Approved: {approved_count}")
    print(f"[SKIP] Duplicates: {duplicate_count}")
    print(f"[ERROR] Errors: {error_count}")

    return approved_count


def main() -> None:
    print("Approve Anki Card Candidates")
    print("=" * 60)

    config = load_config()

    candidate_path = Path(config["outputs"]["anki_card_candidates"])
    payload = load_candidates(candidate_path)

    approved_count = approve_pending_candidates(config, payload)

    save_candidates(candidate_path, payload)

    print("\nSummary")
    print("-" * 60)
    print(f"[OK] Approved cards: {approved_count}")
    print(f"[OK] Updated candidate file: {candidate_path}")


if __name__ == "__main__":
    main()