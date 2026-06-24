from __future__ import annotations

import argparse
import json
import os
import re
import site
import sys
from datetime import datetime
from pathlib import Path


CONFIG_PATH = Path("configs/languageos.config.json")


LANGUAGE_MAP = {
    "auto": None,
    "english": "en",
    "en": "en",
    "german": "de",
    "de": "de",
}


# Keep DLL directory handles alive for the lifetime of the process.
# On Windows, os.add_dll_directory returns a handle. If it is garbage-collected
# or closed too early, Windows may stop searching that directory for DLLs.
_DLL_DIRECTORY_HANDLES = []


def add_windows_nvidia_dll_paths() -> None:
    """
    Add NVIDIA CUDA/cuDNN DLL directories installed inside the current .venv.

    This makes faster-whisper GPU mode work without manually running:

    $env:PATH = "...nvidia\\cublas\\bin;...nvidia\\cudnn\\bin;..."

    Expected DLLs:
    - cublas64_12.dll
    - cublasLt64_12.dll
    - cudnn64_9.dll
    """
    if os.name != "nt":
        return

    candidate_site_packages: list[Path] = []

    try:
        for path_text in site.getsitepackages():
            candidate_site_packages.append(Path(path_text))
    except Exception:
        pass

    candidate_site_packages.append(Path(sys.prefix) / "Lib" / "site-packages")

    dll_dirs: list[Path] = []

    for site_packages in candidate_site_packages:
        nvidia_root = site_packages / "nvidia"

        possible_dirs = [
            nvidia_root / "cublas" / "bin",
            nvidia_root / "cudnn" / "bin",
            nvidia_root / "cuda_nvrtc" / "bin",
        ]

        for dll_dir in possible_dirs:
            if dll_dir.exists() and dll_dir not in dll_dirs:
                dll_dirs.append(dll_dir)

    if not dll_dirs:
        return

    existing_path = os.environ.get("PATH", "")
    path_parts = existing_path.split(os.pathsep)

    for dll_dir in dll_dirs:
        dll_dir_text = str(dll_dir)

        if dll_dir_text not in path_parts:
            os.environ["PATH"] = dll_dir_text + os.pathsep + os.environ.get("PATH", "")

        try:
            handle = os.add_dll_directory(dll_dir_text)
            _DLL_DIRECTORY_HANDLES.append(handle)
        except Exception:
            # PATH update above is still useful even if add_dll_directory fails.
            pass


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
        return "transcript"

    return text[:120]


def format_timestamp(seconds: float) -> str:
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60

    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def build_plain_text(segments: list[dict]) -> str:
    lines: list[str] = []

    for segment in segments:
        text = segment["text"].strip()

        if text:
            lines.append(text)

    return "\n".join(lines).strip() + "\n"


def build_markdown_note(
    source_path: Path,
    model_name: str,
    language: str,
    detected_language: str | None,
    duration_seconds: float | None,
    segments: list[dict],
) -> str:
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    plain_text = build_plain_text(segments)

    duration_text = ""
    if duration_seconds is not None:
        duration_text = format_timestamp(duration_seconds)

    lines: list[str] = []

    lines.append("---")
    lines.append("type: listening_transcript")
    lines.append(f"source_file: {source_path.name}")
    lines.append(f"source_path: {source_path}")
    lines.append(f"model: {model_name}")
    lines.append(f"language_setting: {language}")
    lines.append(f"detected_language: {detected_language or ''}")
    lines.append(f"duration: {duration_text}")
    lines.append(f"created_at: {created_at}")
    lines.append("status: raw_transcript")
    lines.append("---")
    lines.append("")
    lines.append(f"# Transcript - {source_path.stem}")
    lines.append("")
    lines.append("## Metadata")
    lines.append("")
    lines.append(f"- Source: `{source_path}`")
    lines.append(f"- Model: `{model_name}`")
    lines.append(f"- Language setting: `{language}`")
    lines.append(f"- Detected language: `{detected_language or 'unknown'}`")
    lines.append(f"- Duration: `{duration_text or 'unknown'}`")
    lines.append(f"- Created at: `{created_at}`")
    lines.append("")
    lines.append("## Full Transcript")
    lines.append("")
    lines.append(plain_text)
    lines.append("")
    lines.append("## Timestamped Transcript")
    lines.append("")

    for segment in segments:
        start = format_timestamp(segment["start"])
        end = format_timestamp(segment["end"])
        text = segment["text"].strip()

        if text:
            lines.append(f"- `[{start} - {end}]` {text}")

    lines.append("")
    lines.append("## Learning Extraction")
    lines.append("")
    lines.append("### Useful Sentences")
    lines.append("")
    lines.append("| Sentence | Meaning | Note | Anki? |")
    lines.append("|---|---|---|---|")
    lines.append("")
    lines.append("### Vocabulary")
    lines.append("")
    lines.append("| Word / Phrase | Meaning | Example Sentence | Source |")
    lines.append("|---|---|---|---|")
    lines.append("")
    lines.append("### Notes")
    lines.append("")

    return "\n".join(lines)


def transcribe_file(
    input_path: Path,
    model_name: str,
    language: str,
    device: str,
    compute_type: str,
    beam_size: int,
) -> tuple[list[dict], str | None, float | None]:
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    if device == "cuda":
        add_windows_nvidia_dll_paths()

    from faster_whisper import WhisperModel

    language_code = LANGUAGE_MAP.get(language.lower())

    print(f"[OK] Loading model: {model_name}")
    print(f"[OK] Device: {device}")
    print(f"[OK] Compute type: {compute_type}")

    model = WhisperModel(
        model_name,
        device=device,
        compute_type=compute_type,
    )

    print(f"[OK] Transcribing: {input_path}")

    segments_iter, info = model.transcribe(
        str(input_path),
        language=language_code,
        beam_size=beam_size,
        vad_filter=True,
    )

    segments: list[dict] = []

    for segment in segments_iter:
        item = {
            "start": float(segment.start),
            "end": float(segment.end),
            "text": segment.text,
        }

        segments.append(item)

        start = format_timestamp(item["start"])
        end = format_timestamp(item["end"])
        print(f"[{start} - {end}] {item['text'].strip()}")

    detected_language = getattr(info, "language", None)
    duration_seconds = getattr(info, "duration", None)

    return segments, detected_language, duration_seconds


def save_outputs(
    config: dict,
    input_path: Path,
    model_name: str,
    language: str,
    detected_language: str | None,
    duration_seconds: float | None,
    segments: list[dict],
) -> tuple[Path, Path]:
    languageos_root = Path(config["languageos_root"])
    obsidian_vault = Path(config["obsidian_vault"])

    raw_output_dir = languageos_root / "Media" / "Transcripts"
    obsidian_output_dir = obsidian_vault / "Listening" / "Transcripts"

    raw_output_dir.mkdir(parents=True, exist_ok=True)
    obsidian_output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_stem = sanitize_filename(input_path.stem)

    raw_txt_path = raw_output_dir / f"{timestamp}_{safe_stem}.{model_name}.txt"
    md_path = obsidian_output_dir / f"{timestamp}_{safe_stem}.{model_name}.md"

    raw_txt_path.write_text(
        build_plain_text(segments),
        encoding="utf-8",
    )

    md_path.write_text(
        build_markdown_note(
            source_path=input_path,
            model_name=model_name,
            language=language,
            detected_language=detected_language,
            duration_seconds=duration_seconds,
            segments=segments,
        ),
        encoding="utf-8",
    )

    return raw_txt_path, md_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transcribe audio/video files with faster-whisper.",
    )

    parser.add_argument(
        "input",
        help="Path to input audio/video file.",
    )

    parser.add_argument(
        "--model",
        default="small",
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="Whisper model name. Recommended: small for daily, medium for quality.",
    )

    parser.add_argument(
        "--language",
        default="auto",
        choices=["auto", "english", "en", "german", "de"],
        help="Language hint. Use auto, english/en, or german/de.",
    )

    parser.add_argument(
        "--device",
        default="cuda",
        choices=["cuda", "cpu"],
        help="Device to run transcription on.",
    )

    parser.add_argument(
        "--compute-type",
        default="int8_float16",
        help="Compute type. Recommended for RTX 3050 4GB: int8_float16.",
    )

    parser.add_argument(
        "--beam-size",
        type=int,
        default=5,
        help="Beam size for decoding.",
    )

    args = parser.parse_args()

    print("LanguageOS Transcribe Audio")
    print("=" * 60)

    config = load_config()

    input_path = Path(args.input).expanduser().resolve()

    segments, detected_language, duration_seconds = transcribe_file(
        input_path=input_path,
        model_name=args.model,
        language=args.language,
        device=args.device,
        compute_type=args.compute_type,
        beam_size=args.beam_size,
    )

    raw_txt_path, md_path = save_outputs(
        config=config,
        input_path=input_path,
        model_name=args.model,
        language=args.language,
        detected_language=detected_language,
        duration_seconds=duration_seconds,
        segments=segments,
    )

    print("\nSummary")
    print("-" * 60)
    print(f"[OK] Segments: {len(segments)}")
    print(f"[OK] Detected language: {detected_language}")
    print(f"[OK] Raw transcript: {raw_txt_path}")
    print(f"[OK] Obsidian note: {md_path}")


if __name__ == "__main__":
    main()