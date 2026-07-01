from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


@dataclass(frozen=True)
class ExternalAppConfig:
    vault_path: Path
    obsidian_vault_name: str
    anki_executable: str
    anki_connect_url: str = "http://127.0.0.1:8765"

    @classmethod
    def load(
        cls, *, vault_path: Path, config_path: Path | None = None
    ) -> ExternalAppConfig:
        default = cls(
            vault_path=vault_path,
            obsidian_vault_name=vault_path.name,
            anki_executable="",
            anki_connect_url="http://127.0.0.1:8765",
        )

        if config_path is None or not config_path.exists():
            return default

        data = json.loads(config_path.read_text(encoding="utf-8"))

        obsidian = data.get("obsidian", {})
        anki = data.get("anki", {})

        if not isinstance(obsidian, dict):
            obsidian = {}

        if not isinstance(anki, dict):
            anki = {}

        return cls(
            vault_path=vault_path,
            obsidian_vault_name=str(
                obsidian.get("vault_name") or default.obsidian_vault_name
            ),
            anki_executable=str(anki.get("executable") or default.anki_executable),
            anki_connect_url=str(anki.get("connect_url") or default.anki_connect_url),
        )


@dataclass(frozen=True)
class ExternalAppResult:
    success: bool
    message: str
    details: str = ""


@dataclass(frozen=True)
class AnkiConnectStatus:
    online: bool
    version: int | None
    message: str


class ExternalAppService:
    """
    Handles opening external learner tools.

    UI code should call this service instead of knowing app-specific URI/path logic.
    """

    def __init__(self, config: ExternalAppConfig) -> None:
        self.config = config

    def build_obsidian_uri(self, file_path: str | Path) -> str:
        path = Path(file_path).resolve()
        vault_root = self.config.vault_path.resolve()

        try:
            relative_path = path.relative_to(vault_root)
        except ValueError as exc:
            raise ValueError(
                f"File is not inside configured vault: {path} not under {vault_root}"
            ) from exc

        relative_posix = relative_path.as_posix()

        vault = quote(self.config.obsidian_vault_name, safe="")
        file_value = quote(relative_posix, safe="/")

        return f"obsidian://open?vault={vault}&file={file_value}"

    def open_obsidian_note(self, file_path: str | Path) -> ExternalAppResult:
        try:
            uri = self.build_obsidian_uri(file_path)
            self._open_uri(uri)
            return ExternalAppResult(
                success=True,
                message="Opening note in Obsidian.",
                details=uri,
            )
        except Exception as exc:
            return ExternalAppResult(
                success=False,
                message="Could not open Obsidian note.",
                details=str(exc),
            )

    def open_anki_app(self) -> ExternalAppResult:
        candidates = self._anki_executable_candidates()

        for candidate in candidates:
            try:
                self._open_executable(candidate)
                return ExternalAppResult(
                    success=True,
                    message="Opening Anki.",
                    details=str(candidate),
                )
            except Exception:
                continue

        return ExternalAppResult(
            success=False,
            message="Could not open Anki.",
            details=(
                "Set anki.executable in configs/local_apps.json, or add Anki to PATH."
            ),
        )

    def check_anki_connect(self, *, timeout_seconds: float = 1.5) -> AnkiConnectStatus:
        payload = json.dumps(
            {
                "action": "version",
                "version": 6,
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            self.config.anki_connect_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")

            data = json.loads(raw)
            version = data.get("result")

            if isinstance(version, int):
                return AnkiConnectStatus(
                    online=True,
                    version=version,
                    message=f"AnkiConnect online. Version: {version}",
                )

            return AnkiConnectStatus(
                online=False,
                version=None,
                message=f"Unexpected AnkiConnect response: {raw}",
            )

        except urllib.error.URLError:
            return AnkiConnectStatus(
                online=False,
                version=None,
                message=(
                    "AnkiConnect is offline. Open Anki and make sure the "
                    "AnkiConnect add-on is installed."
                ),
            )
        except Exception as exc:
            return AnkiConnectStatus(
                online=False,
                version=None,
                message=f"AnkiConnect check failed: {exc}",
            )

    def _open_uri(self, uri: str) -> None:
        if os.name == "nt":
            os.startfile(uri)  # type: ignore[attr-defined]
            return

        webbrowser.open(uri)

    def _open_executable(self, executable: str | Path) -> None:
        executable_text = str(executable).strip()

        if not executable_text:
            raise ValueError("Empty executable path.")

        executable_path = Path(executable_text)

        if executable_path.exists():
            if os.name == "nt":
                os.startfile(str(executable_path))  # type: ignore[attr-defined]
            else:
                subprocess.Popen([str(executable_path)])
            return

        subprocess.Popen([executable_text])

    def _anki_executable_candidates(self) -> list[str]:
        candidates: list[str] = []

        if self.config.anki_executable.strip():
            candidates.append(self.config.anki_executable.strip())

        local_app_data = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        program_files_x86 = os.environ.get(
            "ProgramFiles(x86)", r"C:\Program Files (x86)"
        )

        candidates.extend(
            [
                str(Path(program_files) / "Anki" / "anki.exe"),
                str(Path(program_files_x86) / "Anki" / "anki.exe"),
            ]
        )

        if local_app_data:
            candidates.extend(
                [
                    str(Path(local_app_data) / "Programs" / "Anki" / "anki.exe"),
                    str(Path(local_app_data) / "Anki" / "anki.exe"),
                ]
            )

        candidates.append("anki")

        deduped: list[str] = []
        seen: set[str] = set()

        for candidate in candidates:
            key = candidate.casefold()
            if key not in seen:
                seen.add(key)
                deduped.append(candidate)

        return deduped
