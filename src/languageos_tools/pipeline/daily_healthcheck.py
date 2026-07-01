from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HealthcheckStep:
    name: str
    command: tuple[str, ...]
    expected_stdout_contains: tuple[str, ...] = ()
    required: bool = True


@dataclass(frozen=True)
class HealthcheckStepResult:
    name: str
    command: tuple[str, ...]
    return_code: int
    duration_seconds: float
    passed: bool
    stdout: str
    stderr: str
    expected_stdout_contains: tuple[str, ...]
    missing_expected_output: tuple[str, ...]

    @property
    def status(self) -> str:
        return "PASS" if self.passed else "FAIL"


@dataclass(frozen=True)
class HealthcheckReport:
    started_at: str
    finished_at: str
    project_root: str
    vault_path: str
    db_path: str
    passed: bool
    step_results: tuple[HealthcheckStepResult, ...]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "project_root": self.project_root,
            "vault_path": self.vault_path,
            "db_path": self.db_path,
            "passed": self.passed,
            "summary": {
                "steps": len(self.step_results),
                "passed": sum(1 for result in self.step_results if result.passed),
                "failed": sum(1 for result in self.step_results if not result.passed),
            },
            "step_results": [
                {
                    **dataclasses.asdict(result),
                    "command": list(result.command),
                    "expected_stdout_contains": list(result.expected_stdout_contains),
                    "missing_expected_output": list(result.missing_expected_output),
                }
                for result in self.step_results
            ],
        }

    def write_json(self, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(self.to_json_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class DailyHealthcheckService:
    """
    Runs the quick LanguageOS daily healthcheck.

    This is intentionally a thin orchestration layer. Each real operation stays
    in its own existing service/CLI.
    """

    def __init__(
        self,
        *,
        project_root: Path,
        vault_path: Path,
        db_path: Path,
        python_executable: Path | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.vault_path = vault_path
        self.db_path = db_path
        self.python_executable = python_executable or Path(sys.executable)

    def run(
        self,
        *,
        output_json: Path | None = None,
        skip_build: bool = False,
        skip_lookup_smoke_tests: bool = False,
        continue_on_error: bool = False,
    ) -> HealthcheckReport:
        started_at = datetime.now().isoformat(timespec="seconds")
        results: list[HealthcheckStepResult] = []

        for step in self._build_steps(
            skip_build=skip_build,
            skip_lookup_smoke_tests=skip_lookup_smoke_tests,
        ):
            result = self._run_step(step)
            results.append(result)

            if not result.passed and step.required and not continue_on_error:
                break

        finished_at = datetime.now().isoformat(timespec="seconds")
        report = HealthcheckReport(
            started_at=started_at,
            finished_at=finished_at,
            project_root=str(self.project_root),
            vault_path=str(self.vault_path),
            db_path=str(self.db_path),
            passed=all(result.passed for result in results),
            step_results=tuple(results),
        )

        if output_json is not None:
            report.write_json(output_json)

        return report

    def _build_steps(
        self,
        *,
        skip_build: bool,
        skip_lookup_smoke_tests: bool,
    ) -> tuple[HealthcheckStep, ...]:
        steps: list[HealthcheckStep] = []

        steps.append(
            HealthcheckStep(
                name="Schema validation",
                command=(
                    str(self.python_executable),
                    "scripts/validate_schema.py",
                    "--vault",
                    str(self.vault_path),
                ),
                expected_stdout_contains=("Errors          : 0",),
            )
        )

        if not skip_build:
            steps.extend(
                [
                    HealthcheckStep(
                        name="Build language DB",
                        command=(
                            str(self.python_executable),
                            "scripts/build_language_db.py",
                        ),
                    ),
                    HealthcheckStep(
                        name="Rebuild relation index",
                        command=(
                            str(self.python_executable),
                            "scripts/rebuild_relation_index.py",
                        ),
                    ),
                ]
            )

        steps.append(
            HealthcheckStep(
                name="Item key audit",
                command=(
                    str(self.python_executable),
                    "scripts/audit_item_keys.py",
                    "--vault",
                    str(self.vault_path),
                    "--db",
                    str(self.db_path),
                    "--changed-only",
                ),
                expected_stdout_contains=("Changed records  : 0",),
            )
        )

        steps.append(
            HealthcheckStep(
                name="Relation integrity audit",
                command=(
                    str(self.python_executable),
                    "scripts/audit_relation_integrity.py",
                    "--db",
                    str(self.db_path),
                    "--vault",
                    str(self.vault_path),
                ),
                expected_stdout_contains=("Errors          : 0",),
            )
        )

        if not skip_lookup_smoke_tests:
            steps.extend(
                [
                    HealthcheckStep(
                        name="Lookup smoke: trotzdem",
                        command=(
                            str(self.python_executable),
                            "scripts/lookup_items.py",
                            "trotzdem",
                            "--language",
                            "german",
                            "--with-relations",
                        ),
                        expected_stdout_contains=(
                            "vocabulary|german|trotzdem",
                            "grammar|german|contrast connectors",
                        ),
                    ),
                    HealthcheckStep(
                        name="Lookup smoke: contrast grammar",
                        command=(
                            str(self.python_executable),
                            "scripts/lookup_items.py",
                            "contrast",
                            "--type",
                            "grammar",
                            "--with-relations",
                        ),
                        expected_stdout_contains=(
                            "grammar|german|contrast connectors",
                        ),
                    ),
                    HealthcheckStep(
                        name="Lookup smoke: ich lerne sentence",
                        command=(
                            str(self.python_executable),
                            "scripts/lookup_items.py",
                            "ich lerne",
                            "--type",
                            "sentence",
                            "--language",
                            "german",
                            "--with-relations",
                        ),
                        expected_stdout_contains=(
                            "sentence|german|ich lerne jeden tag deutsch",
                        ),
                    ),
                ]
            )

        return tuple(steps)

    def _run_step(self, step: HealthcheckStep) -> HealthcheckStepResult:
        started = time.perf_counter()

        process = subprocess.run(
            step.command,
            cwd=str(self.project_root),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )

        duration = time.perf_counter() - started
        missing_expected_output = tuple(
            expected
            for expected in step.expected_stdout_contains
            if expected not in process.stdout
        )

        passed = process.returncode == 0 and not missing_expected_output

        return HealthcheckStepResult(
            name=step.name,
            command=step.command,
            return_code=process.returncode,
            duration_seconds=round(duration, 3),
            passed=passed,
            stdout=process.stdout,
            stderr=process.stderr,
            expected_stdout_contains=step.expected_stdout_contains,
            missing_expected_output=missing_expected_output,
        )


def build_arg_parser() -> argparse.ArgumentParser:
    project_root = Path(__file__).resolve().parents[3]

    parser = argparse.ArgumentParser(
        description="Run the quick LanguageOS daily healthcheck pipeline.",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=project_root,
        help="Project root path.",
    )
    parser.add_argument(
        "--vault",
        type=Path,
        default=Path(r"D:\LanguageOS\Obsidian\LanguageOS_vault"),
        help="Obsidian vault path.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(r"D:\LanguageOS\Inbox\Indexes\languageos.db"),
        help="LanguageOS SQLite DB path.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path(r"D:\LanguageOS\Inbox\Indexes\daily_healthcheck_v1.json"),
        help="JSON report path.",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip build_language_db.py and rebuild_relation_index.py.",
    )
    parser.add_argument(
        "--skip-lookup-smoke-tests",
        action="store_true",
        help="Skip lookup smoke tests.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue running later steps even if an earlier step fails.",
    )
    return parser


def print_report(report: HealthcheckReport) -> None:
    print("LanguageOS Daily Healthcheck v1")
    print("=" * 80)
    print(f"Started : {report.started_at}")
    print(f"Finished: {report.finished_at}")
    print(f"Project : {report.project_root}")
    print(f"Vault   : {report.vault_path}")
    print(f"DB      : {report.db_path}")
    print(f"Status  : {'PASS' if report.passed else 'FAIL'}")
    print("-" * 80)

    for index, result in enumerate(report.step_results, start=1):
        print(f"[{index}] {result.status} {result.name}")
        print(f"    return_code: {result.return_code}")
        print(f"    duration   : {result.duration_seconds}s")

        if result.missing_expected_output:
            print("    missing expected output:")
            for missing in result.missing_expected_output:
                print(f"      - {missing}")

        if not result.passed:
            print("    command:")
            print("      " + " ".join(result.command))

            if result.stdout.strip():
                print("    stdout:")
                print(_indent(result.stdout.rstrip(), "      "))

            if result.stderr.strip():
                print("    stderr:")
                print(_indent(result.stderr.rstrip(), "      "))


def _indent(text: str, prefix: str) -> str:
    return "\n".join(prefix + line for line in text.splitlines())


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    parser = build_arg_parser()
    args = parser.parse_args(argv)

    service = DailyHealthcheckService(
        project_root=args.project_root,
        vault_path=args.vault,
        db_path=args.db,
    )
    report = service.run(
        output_json=args.output_json,
        skip_build=args.skip_build,
        skip_lookup_smoke_tests=args.skip_lookup_smoke_tests,
        continue_on_error=args.continue_on_error,
    )

    print_report(report)

    if args.output_json is not None:
        print("-" * 80)
        print(f"JSON report written: {args.output_json}")

    return 0 if report.passed else 1
