from __future__ import annotations

import asyncio
import dataclasses
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class CommandSpec:
    name: str
    args: tuple[str, ...]
    expected_stdout_contains: tuple[str, ...] = ()
    timeout_seconds: int = 120


@dataclass(frozen=True)
class CommandResult:
    name: str
    args: tuple[str, ...]
    return_code: int
    duration_seconds: float
    stdout: str
    stderr: str
    expected_stdout_contains: tuple[str, ...]
    missing_expected_output: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.return_code == 0 and not self.missing_expected_output

    @property
    def status(self) -> str:
        return "PASS" if self.passed else "FAIL"

    def to_display_text(self) -> str:
        command_text = " ".join(self.args)
        lines: list[str] = []

        lines.append(f"[{self.status}] {self.name}")
        lines.append("=" * 80)
        lines.append(f"Command : {command_text}")
        lines.append(f"Return  : {self.return_code}")
        lines.append(f"Duration: {self.duration_seconds:.3f}s")

        if self.missing_expected_output:
            lines.append("")
            lines.append("Missing expected output:")
            for missing in self.missing_expected_output:
                lines.append(f"  - {missing}")

        if self.stdout.strip():
            lines.append("")
            lines.append("STDOUT")
            lines.append("-" * 80)
            lines.append(self.stdout.rstrip())

        if self.stderr.strip():
            lines.append("")
            lines.append("STDERR")
            lines.append("-" * 80)
            lines.append(self.stderr.rstrip())

        return "\n".join(lines)

    def to_json_dict(self) -> dict[str, object]:
        return {
            **dataclasses.asdict(self),
            "args": list(self.args),
            "expected_stdout_contains": list(self.expected_stdout_contains),
            "missing_expected_output": list(self.missing_expected_output),
            "passed": self.passed,
            "status": self.status,
        }


class CommandRunner:
    """
    Async command runner for the local LanguageOS UI.

    UI layer uses this helper instead of directly calling subprocess everywhere.
    """

    def __init__(
        self,
        *,
        project_root: Path,
        python_executable: Path | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.python_executable = python_executable or Path(sys.executable)

    def python_command(self, script_path: str, *args: str) -> tuple[str, ...]:
        return (
            str(self.python_executable),
            script_path,
            *args,
        )

    async def run(self, spec: CommandSpec) -> CommandResult:
        started = time.perf_counter()

        process = await asyncio.create_subprocess_exec(
            *spec.args,
            cwd=str(self.project_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=spec.timeout_seconds,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

            duration = time.perf_counter() - started
            return CommandResult(
                name=spec.name,
                args=spec.args,
                return_code=124,
                duration_seconds=duration,
                stdout="",
                stderr=f"Command timed out after {spec.timeout_seconds} seconds.",
                expected_stdout_contains=spec.expected_stdout_contains,
                missing_expected_output=spec.expected_stdout_contains,
            )

        duration = time.perf_counter() - started
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        missing_expected_output = tuple(
            expected
            for expected in spec.expected_stdout_contains
            if expected not in stdout
        )

        return CommandResult(
            name=spec.name,
            args=spec.args,
            return_code=int(process.returncode or 0),
            duration_seconds=duration,
            stdout=stdout,
            stderr=stderr,
            expected_stdout_contains=spec.expected_stdout_contains,
            missing_expected_output=missing_expected_output,
        )


def make_command_spec(
    *,
    name: str,
    args: Sequence[str],
    expected_stdout_contains: Sequence[str] = (),
    timeout_seconds: int = 120,
) -> CommandSpec:
    return CommandSpec(
        name=name,
        args=tuple(args),
        expected_stdout_contains=tuple(expected_stdout_contains),
        timeout_seconds=timeout_seconds,
    )