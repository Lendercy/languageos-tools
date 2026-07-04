from __future__ import annotations

import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class HealthCheckResult:
    name: str
    ok: bool
    message: str


@dataclass(frozen=True)
class WorkspaceHealthReport:
    checked_at: datetime
    db_path: Path
    db_exists: bool
    db_size_bytes: int
    language_item_count: int | None
    relation_count: int | None
    checks: tuple[HealthCheckResult, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)


@dataclass(frozen=True)
class MaintenanceCommandResult:
    command_name: str
    success: bool
    command: tuple[str, ...]
    stdout: str
    stderr: str
    returncode: int | None
    dry_run: bool

    @property
    def message(self) -> str:
        if self.dry_run:
            return f"Dry run: {' '.join(self.command)}"

        if self.success:
            return f"{self.command_name} completed."

        return f"{self.command_name} failed."


class MaintenanceService:
    """
    Backend service for learner workspace maintenance actions.

    The service is intentionally conservative:
    - It reads health state from the local SQLite DB.
    - It executes only known project scripts.
    - It supports dry-run command preview.
    - It does not delete, merge, or approve learning data.
    """

    def __init__(
        self,
        *,
        project_root: Path,
        db_path: Path,
        python_executable: str | None = None,
    ) -> None:
        self.project_root = project_root
        self.db_path = db_path
        self.python_executable = python_executable or sys.executable

    def healthcheck(self) -> WorkspaceHealthReport:
        checks: list[HealthCheckResult] = []

        db_exists = self.db_path.exists()
        db_size_bytes = self.db_path.stat().st_size if db_exists else 0

        checks.append(
            HealthCheckResult(
                name="database_file",
                ok=db_exists,
                message=(
                    f"Database exists: {self.db_path}"
                    if db_exists
                    else f"Database not found: {self.db_path}"
                ),
            )
        )

        language_item_count: int | None = None
        relation_count: int | None = None

        if not db_exists:
            checks.append(
                HealthCheckResult(
                    name="database_schema",
                    ok=False,
                    message="Cannot inspect schema because database file is missing.",
                )
            )
            checks.append(
                HealthCheckResult(
                    name="relation_index",
                    ok=False,
                    message="Cannot inspect relation index because database file is missing.",
                )
            )

            return WorkspaceHealthReport(
                checked_at=datetime.now(),
                db_path=self.db_path,
                db_exists=False,
                db_size_bytes=db_size_bytes,
                language_item_count=language_item_count,
                relation_count=relation_count,
                checks=tuple(checks),
            )

        try:
            with sqlite3.connect(self.db_path) as conn:
                tables = self._list_tables(conn)

                has_language_items = "language_items" in tables
                checks.append(
                    HealthCheckResult(
                        name="language_items_table",
                        ok=has_language_items,
                        message=(
                            "language_items table exists."
                            if has_language_items
                            else "language_items table is missing."
                        ),
                    )
                )

                if has_language_items:
                    language_item_count = self._count_rows(conn, "language_items")
                    checks.append(
                        HealthCheckResult(
                            name="language_items_count",
                            ok=language_item_count > 0,
                            message=f"Indexed language items: {language_item_count}",
                        )
                    )

                relation_table = self._detect_relation_table(tables)
                has_relation_table = relation_table is not None

                checks.append(
                    HealthCheckResult(
                        name="relation_table",
                        ok=has_relation_table,
                        message=(
                            f"Relation table exists: {relation_table}"
                            if relation_table
                            else "No relation table found."
                        ),
                    )
                )

                if relation_table:
                    relation_count = self._count_rows(conn, relation_table)
                    checks.append(
                        HealthCheckResult(
                            name="relation_count",
                            ok=relation_count >= 0,
                            message=f"Stored relations: {relation_count}",
                        )
                    )

        except sqlite3.Error as exc:
            checks.append(
                HealthCheckResult(
                    name="database_read",
                    ok=False,
                    message=f"Could not read database: {exc}",
                )
            )

        return WorkspaceHealthReport(
            checked_at=datetime.now(),
            db_path=self.db_path,
            db_exists=db_exists,
            db_size_bytes=db_size_bytes,
            language_item_count=language_item_count,
            relation_count=relation_count,
            checks=tuple(checks),
        )

    def build_database(self, *, dry_run: bool = False) -> MaintenanceCommandResult:
        return self._run_project_script(
            command_name="Build language database",
            script_path=Path("scripts") / "build_language_db.py",
            dry_run=dry_run,
        )

    def rebuild_relation_index(
        self,
        *,
        dry_run: bool = False,
    ) -> MaintenanceCommandResult:
        return self._run_project_script(
            command_name="Rebuild relation index",
            script_path=Path("scripts") / "rebuild_relation_index.py",
            dry_run=dry_run,
        )

    def _run_project_script(
        self,
        *,
        command_name: str,
        script_path: Path,
        dry_run: bool,
    ) -> MaintenanceCommandResult:
        absolute_script_path = self.project_root / script_path
        command = (self.python_executable, str(absolute_script_path))

        if dry_run:
            return MaintenanceCommandResult(
                command_name=command_name,
                success=True,
                command=command,
                stdout="",
                stderr="",
                returncode=None,
                dry_run=True,
            )

        if not absolute_script_path.exists():
            return MaintenanceCommandResult(
                command_name=command_name,
                success=False,
                command=command,
                stdout="",
                stderr=f"Script not found: {absolute_script_path}",
                returncode=None,
                dry_run=False,
            )

        completed = subprocess.run(
            command,
            cwd=self.project_root,
            capture_output=True,
            text=True,
            check=False,
        )

        return MaintenanceCommandResult(
            command_name=command_name,
            success=completed.returncode == 0,
            command=command,
            stdout=completed.stdout,
            stderr=completed.stderr,
            returncode=completed.returncode,
            dry_run=False,
        )

    def _list_tables(self, conn: sqlite3.Connection) -> set[str]:
        rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            """
        ).fetchall()
        return {str(row[0]) for row in rows}

    def _count_rows(self, conn: sqlite3.Connection, table_name: str) -> int:
        quoted_table_name = table_name.replace('"', '""')
        row = conn.execute(f'SELECT COUNT(*) FROM "{quoted_table_name}"').fetchone()
        return int(row[0]) if row else 0

    def _detect_relation_table(self, tables: set[str]) -> str | None:
        preferred_names = (
            "relations",
            "relation_edges",
            "language_relations",
        )

        for name in preferred_names:
            if name in tables:
                return name

        for name in sorted(tables):
            if "relation" in name:
                return name

        return None