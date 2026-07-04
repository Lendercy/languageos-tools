from __future__ import annotations

import sqlite3
from pathlib import Path

from languageos_tools.ui.services.maintenance_service import MaintenanceService


def test_maintenance_healthcheck_reports_missing_database(tmp_path: Path) -> None:
    db_path = tmp_path / "missing.db"

    service = MaintenanceService(
        project_root=tmp_path,
        db_path=db_path,
        python_executable="python",
    )

    report = service.healthcheck()

    assert report.db_exists is False
    assert report.ok is False
    assert report.language_item_count is None
    assert report.relation_count is None
    assert any(check.name == "database_file" for check in report.checks)


def test_maintenance_healthcheck_counts_items_and_relations(tmp_path: Path) -> None:
    db_path = tmp_path / "languageos.db"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE language_items (
                item_key TEXT PRIMARY KEY,
                language TEXT NOT NULL,
                item_type TEXT NOT NULL,
                title TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE relations (
                source_item_key TEXT NOT NULL,
                target_item_key TEXT NOT NULL,
                relation_type TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO language_items (
                item_key,
                language,
                item_type,
                title
            )
            VALUES (
                'vocabulary|german|trotzdem',
                'german',
                'vocabulary',
                'trotzdem'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO relations (
                source_item_key,
                target_item_key,
                relation_type
            )
            VALUES (
                'vocabulary|german|trotzdem',
                'grammar|german|contrast connectors',
                'uses_grammar'
            )
            """
        )

    service = MaintenanceService(
        project_root=tmp_path,
        db_path=db_path,
        python_executable="python",
    )

    report = service.healthcheck()

    assert report.db_exists is True
    assert report.language_item_count == 1
    assert report.relation_count == 1
    assert report.ok is True


def test_maintenance_build_database_dry_run(tmp_path: Path) -> None:
    service = MaintenanceService(
        project_root=tmp_path,
        db_path=tmp_path / "languageos.db",
        python_executable="python",
    )

    result = service.build_database(dry_run=True)

    assert result.success is True
    assert result.dry_run is True
    assert result.returncode is None
    assert "build_language_db.py" in " ".join(result.command)


def test_maintenance_rebuild_relation_index_dry_run(tmp_path: Path) -> None:
    service = MaintenanceService(
        project_root=tmp_path,
        db_path=tmp_path / "languageos.db",
        python_executable="python",
    )

    result = service.rebuild_relation_index(dry_run=True)

    assert result.success is True
    assert result.dry_run is True
    assert result.returncode is None
    assert "rebuild_relation_index.py" in " ".join(result.command)