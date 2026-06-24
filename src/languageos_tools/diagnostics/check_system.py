from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests import RequestException


CONFIG_PATH = Path("configs/languageos.config.json")


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def check_path(label: str, path_text: str) -> bool:
    path = Path(path_text)
    exists = path.exists()

    status = "OK" if exists else "MISSING"
    print(f"[{status}] {label}: {path}")

    return exists


def check_output_parent(label: str, path_text: str) -> bool:
    path = Path(path_text)
    parent = path.parent
    exists = parent.exists()

    status = "OK" if exists else "MISSING"
    print(f"[{status}] {label} parent: {parent}")

    return exists


def check_ffmpeg() -> bool:
    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")

    ok = bool(ffmpeg_path and ffprobe_path)

    if ffmpeg_path:
        print(f"[OK] ffmpeg: {ffmpeg_path}")
    else:
        print("[MISSING] ffmpeg not found in PATH")

    if ffprobe_path:
        print(f"[OK] ffprobe: {ffprobe_path}")
    else:
        print("[MISSING] ffprobe not found in PATH")

    if ok:
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )

            first_line = result.stdout.splitlines()[0] if result.stdout else "No version output"
            print(f"[OK] ffmpeg version: {first_line}")

        except Exception as exc:
            print(f"[WARNING] ffmpeg exists but version check failed: {exc}")

    return ok


def validate_url(url: str) -> bool:
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        print(f"[ERROR] Invalid URL scheme for AnkiConnect: {url}")
        return False

    if not parsed.hostname:
        print(f"[ERROR] Invalid AnkiConnect URL, missing hostname: {url}")
        return False

    return True


def check_anki_connect(url: str) -> bool:
    if not validate_url(url):
        return False

    payload = {
        "action": "version",
        "version": 6,
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=3,
        )

        response.raise_for_status()
        data = response.json()

        if data.get("error") is None:
            print(f"[OK] AnkiConnect: {url}, version={data.get('result')}")
            return True

        print(f"[ERROR] AnkiConnect returned error: {data.get('error')}")
        return False

    except RequestException as exc:
        print(f"[MISSING] AnkiConnect not reachable at {url}")
        print(f"          {exc}")
        print("Hint: Open Anki, make sure AnkiConnect is enabled, then run diagnostics again.")
        return False

    except ValueError as exc:
        print(f"[ERROR] AnkiConnect response was not valid JSON at {url}")
        print(f"        {exc}")
        return False


def check_python_package(package_name: str, import_name: str | None = None) -> bool:
    import importlib.util

    module_name = import_name or package_name
    found = importlib.util.find_spec(module_name) is not None

    status = "OK" if found else "MISSING"
    print(f"[{status}] Python package: {package_name}")

    return found


def main() -> None:
    print("LanguageOS Diagnostics")
    print("=" * 60)

    config = load_config()

    print("\n[1] Checking core paths")
    print("-" * 60)

    all_ok = True

    all_ok &= check_path("languageos_root", config["languageos_root"])
    all_ok &= check_path("obsidian_vault", config["obsidian_vault"])

    for label, path_text in config["required_paths"].items():
        all_ok &= check_path(label, path_text)

    print("\n[2] Checking output folders")
    print("-" * 60)

    outputs = config.get("outputs", {})

    for label, path_text in outputs.items():
        if label.endswith("_dir"):
            all_ok &= check_path(label, path_text)
        else:
            all_ok &= check_output_parent(label, path_text)

    print("\n[3] Checking external tools")
    print("-" * 60)

    all_ok &= check_ffmpeg()
    all_ok &= check_anki_connect(config["external_tools"]["anki_connect_url"])

    print("\n[4] Checking Python packages")
    print("-" * 60)

    all_ok &= check_python_package("requests")
    all_ok &= check_python_package("edge-tts", "edge_tts")
    all_ok &= check_python_package("faster-whisper", "faster_whisper")

    print("\n[5] Summary")
    print("-" * 60)

    if all_ok:
        print("[PASS] LanguageOS foundation looks healthy.")
    else:
        print("[FAIL] Some checks failed.")
        print("Fix missing items before adding more automation.")


if __name__ == "__main__":
    main()