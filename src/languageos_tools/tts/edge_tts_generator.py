from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import datetime
from pathlib import Path

import edge_tts

CONFIG_PATH = Path("configs/languageos.config.json")


DEFAULT_VOICES = {
    "german_female": "de-DE-KatjaNeural",
    "german_male": "de-DE-ConradNeural",
    "english_female": "en-US-JennyNeural",
    "english_male": "en-US-GuyNeural",
}


LANGUAGE_TO_DEFAULT_VOICE = {
    "german": DEFAULT_VOICES["german_male"],
    "de": DEFAULT_VOICES["german_male"],
    "english": DEFAULT_VOICES["english_female"],
    "en": DEFAULT_VOICES["english_female"],
}


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def sanitize_filename(text: str) -> str:
    text = text.strip()
    text = re.sub(r"[^\w\s.-]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", "_", text)
    text = text.strip("._")

    if not text:
        return "tts_audio"

    return text[:80]


def resolve_voice(language: str, voice: str | None) -> str:
    if voice:
        return voice

    normalized_language = language.strip().lower()

    if normalized_language in LANGUAGE_TO_DEFAULT_VOICE:
        return LANGUAGE_TO_DEFAULT_VOICE[normalized_language]

    return DEFAULT_VOICES["english_female"]


async def generate_tts_audio(
    text: str,
    output_path: Path,
    voice: str,
    rate: str,
    volume: str,
    pitch: str,
) -> None:
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        volume=volume,
        pitch=pitch,
    )

    await communicate.save(str(output_path))


def build_obsidian_note(
    text: str,
    audio_path: Path,
    voice: str,
    language: str,
    rate: str,
    volume: str,
    pitch: str,
) -> str:
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines: list[str] = []

    lines.append("---")
    lines.append("type: tts_audio")
    lines.append(f"language: {language}")
    lines.append(f"voice: {voice}")
    lines.append(f"rate: {rate}")
    lines.append(f"volume: {volume}")
    lines.append(f"pitch: {pitch}")
    lines.append(f"audio_file: {audio_path.name}")
    lines.append(f"audio_path: {audio_path}")
    lines.append(f"created_at: {created_at}")
    lines.append("---")
    lines.append("")
    lines.append(f"# TTS Audio - {audio_path.stem}")
    lines.append("")
    lines.append("## Text")
    lines.append("")
    lines.append(text)
    lines.append("")
    lines.append("## Audio")
    lines.append("")
    lines.append(f"`{audio_path}`")
    lines.append("")
    lines.append("## Shadowing Notes")
    lines.append("")
    lines.append("- ")
    lines.append("")

    return "\n".join(lines)


def save_obsidian_note(
    config: dict,
    text: str,
    audio_path: Path,
    voice: str,
    language: str,
    rate: str,
    volume: str,
    pitch: str,
) -> Path:
    obsidian_vault = Path(config["obsidian_vault"])
    output_dir = obsidian_vault / "Speaking" / "TTS"

    output_dir.mkdir(parents=True, exist_ok=True)

    md_path = output_dir / f"{audio_path.stem}.md"

    md_path.write_text(
        build_obsidian_note(
            text=text,
            audio_path=audio_path,
            voice=voice,
            language=language,
            rate=rate,
            volume=volume,
            pitch=pitch,
        ),
        encoding="utf-8",
    )

    return md_path


def generate_output_path(config: dict, text: str, language: str, voice: str) -> Path:
    languageos_root = Path(config["languageos_root"])
    output_dir = languageos_root / "Media" / "TTS"

    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_text = sanitize_filename(text)
    safe_voice = sanitize_filename(voice)

    return output_dir / f"{timestamp}_{language}_{safe_voice}_{safe_text}.mp3"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate TTS audio with Edge TTS.",
    )

    parser.add_argument(
        "--text",
        required=True,
        help="Text to synthesize.",
    )

    parser.add_argument(
        "--language",
        default="german",
        choices=["german", "de", "english", "en"],
        help="Language hint for default voice selection.",
    )

    parser.add_argument(
        "--voice",
        default=None,
        help="Edge TTS voice name. Example: de-DE-KatjaNeural or de-DE-ConradNeural.",
    )

    parser.add_argument(
        "--rate",
        default="+0%",
        help="Speaking rate. Example: +0%, -10%, +10%.",
    )

    parser.add_argument(
        "--volume",
        default="+0%",
        help="Volume. Example: +0%, -10%, +10%.",
    )

    parser.add_argument(
        "--pitch",
        default="+0Hz",
        help="Pitch. Example: +0Hz, -5Hz, +5Hz.",
    )

    args = parser.parse_args()

    print("LanguageOS Edge TTS")
    print("=" * 60)

    config = load_config()

    voice = resolve_voice(
        language=args.language,
        voice=args.voice,
    )

    output_path = generate_output_path(
        config=config,
        text=args.text,
        language=args.language,
        voice=voice,
    )

    print(f"[OK] Text: {args.text}")
    print(f"[OK] Language: {args.language}")
    print(f"[OK] Voice: {voice}")
    print(f"[OK] Output: {output_path}")

    asyncio.run(
        generate_tts_audio(
            text=args.text,
            output_path=output_path,
            voice=voice,
            rate=args.rate,
            volume=args.volume,
            pitch=args.pitch,
        )
    )

    md_path = save_obsidian_note(
        config=config,
        text=args.text,
        audio_path=output_path,
        voice=voice,
        language=args.language,
        rate=args.rate,
        volume=args.volume,
        pitch=args.pitch,
    )

    print("\nSummary")
    print("-" * 60)
    print(f"[OK] Audio created: {output_path}")
    print(f"[OK] Obsidian note: {md_path}")


if __name__ == "__main__":
    main()
