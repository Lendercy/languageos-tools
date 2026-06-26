from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from nicegui import ui

from languageos_tools.ui.services.command_runner import (
    CommandResult,
    CommandRunner,
    CommandSpec,
    make_command_spec,
)


@dataclass(frozen=True)
class LanguageOSUIConfig:
    project_root: Path
    vault_path: Path
    db_path: Path
    host: str = "127.0.0.1"
    port: int = 8080


class LanguageOSControlCenter:
    """
    Local-first control center for LanguageOS.

    This UI intentionally wraps existing scripts/services instead of duplicating
    business logic. The CLI remains the source of truth for operations.
    """

    def __init__(self, config: LanguageOSUIConfig) -> None:
        self.config = config
        self.runner = CommandRunner(project_root=config.project_root)

        self.status_label: ui.label | None = None
        self.last_command_label: ui.label | None = None
        self.output_area: ui.textarea | None = None
        self.lookup_query_input: ui.input | None = None
        self.lookup_type_select: ui.select | None = None
        self.lookup_language_select: ui.select | None = None
        self.lookup_relations_checkbox: ui.checkbox | None = None

    def build(self) -> None:
        ui.colors(
            primary="#2563eb",
            secondary="#475569",
            accent="#16a34a",
            positive="#16a34a",
            negative="#dc2626",
            warning="#f59e0b",
        )

        ui.page_title("LanguageOS Control Center")

        with ui.header().classes("items-center justify-between"):
            ui.label("LanguageOS Control Center").classes(
                "text-xl font-bold tracking-wide"
            )
            ui.label("local-first").classes(
                "text-xs uppercase bg-white text-blue-700 px-2 py-1 rounded"
            )

        with ui.column().classes("w-full max-w-7xl mx-auto p-4 gap-4"):
            self._build_top_cards()

            with ui.tabs().classes("w-full") as tabs:
                dashboard_tab = ui.tab("Dashboard")
                lookup_tab = ui.tab("Lookup")
                maintenance_tab = ui.tab("Maintenance")
                logs_tab = ui.tab("Logs")

            with ui.tab_panels(tabs, value=dashboard_tab).classes("w-full"):
                with ui.tab_panel(dashboard_tab):
                    self._build_dashboard_panel()

                with ui.tab_panel(lookup_tab):
                    self._build_lookup_panel()

                with ui.tab_panel(maintenance_tab):
                    self._build_maintenance_panel()

                with ui.tab_panel(logs_tab):
                    self._build_logs_panel()

    def _build_top_cards(self) -> None:
        with ui.grid(columns=3).classes("w-full gap-4"):
            with ui.card().classes("w-full"):
                ui.label("System Status").classes("text-sm text-slate-500")
                self.status_label = ui.label("UNKNOWN").classes(
                    "text-3xl font-bold text-slate-700"
                )
                ui.label("Run healthcheck to update status.").classes(
                    "text-xs text-slate-500"
                )

            with ui.card().classes("w-full"):
                ui.label("Vault").classes("text-sm text-slate-500")
                ui.label(str(self.config.vault_path)).classes(
                    "text-sm font-mono break-all"
                )

            with ui.card().classes("w-full"):
                ui.label("Database").classes("text-sm text-slate-500")
                ui.label(str(self.config.db_path)).classes(
                    "text-sm font-mono break-all"
                )

    def _build_dashboard_panel(self) -> None:
        with ui.card().classes("w-full"):
            ui.label("Daily Workflow").classes("text-lg font-semibold")
            ui.label(
                "Run the full local-first healthcheck: schema, DB build, relation index, key audit, relation audit, and lookup smoke tests."
            ).classes("text-sm text-slate-600")

            with ui.row().classes("gap-2 mt-2"):
                ui.button(
                    "Run Full Healthcheck",
                    icon="health_and_safety",
                    on_click=lambda: self._run_command(self._daily_healthcheck_spec()),
                ).props("unelevated")

                ui.button(
                    "Fast Healthcheck",
                    icon="bolt",
                    on_click=lambda: self._run_command(
                        self._daily_healthcheck_spec(skip_build=True)
                    ),
                ).props("outline")

        with ui.card().classes("w-full mt-4"):
            ui.label("Quick Actions").classes("text-lg font-semibold")

            with ui.grid(columns=3).classes("w-full gap-2"):
                ui.button(
                    "Validate Schema",
                    icon="fact_check",
                    on_click=lambda: self._run_command(self._schema_validation_spec()),
                ).props("outline")

                ui.button(
                    "Build DB",
                    icon="storage",
                    on_click=lambda: self._run_command(self._build_db_spec()),
                ).props("outline")

                ui.button(
                    "Rebuild Relations",
                    icon="hub",
                    on_click=lambda: self._run_command(self._rebuild_relations_spec()),
                ).props("outline")

                ui.button(
                    "Audit Keys",
                    icon="key",
                    on_click=lambda: self._run_command(self._key_audit_spec()),
                ).props("outline")

                ui.button(
                    "Audit Relation Integrity",
                    icon="account_tree",
                    on_click=lambda: self._run_command(self._relation_integrity_spec()),
                ).props("outline")

    def _build_lookup_panel(self) -> None:
        with ui.card().classes("w-full"):
            ui.label("Lookup Items").classes("text-lg font-semibold")
            ui.label(
                "Search vocabulary, sentence, grammar, transcript, or TTS notes from the local SQLite index."
            ).classes("text-sm text-slate-600")

            with ui.row().classes("w-full gap-3 items-end"):
                self.lookup_query_input = ui.input(
                    label="Query",
                    placeholder="trotzdem / contrast / ich lerne",
                    value="trotzdem",
                ).classes("grow")

                self.lookup_type_select = ui.select(
                    label="Type",
                    options=[
                        "all",
                        "vocabulary",
                        "sentence",
                        "grammar",
                        "listening_transcript",
                        "transcript",
                        "tts_audio",
                    ],
                    value="all",
                ).classes("w-56")

                self.lookup_language_select = ui.select(
                    label="Language",
                    options=["all", "german", "english"],
                    value="all",
                ).classes("w-48")

                self.lookup_relations_checkbox = ui.checkbox(
                    "Relations",
                    value=True,
                )

                ui.button(
                    "Search",
                    icon="search",
                    on_click=self._run_lookup_from_form,
                ).props("unelevated")

            with ui.row().classes("gap-2 mt-3"):
                ui.button(
                    "trotzdem",
                    on_click=lambda: self._run_lookup_preset(
                        query="trotzdem",
                        item_type="all",
                        language="german",
                    ),
                ).props("flat")

                ui.button(
                    "contrast grammar",
                    on_click=lambda: self._run_lookup_preset(
                        query="contrast",
                        item_type="grammar",
                        language="all",
                    ),
                ).props("flat")

                ui.button(
                    "ich lerne",
                    on_click=lambda: self._run_lookup_preset(
                        query="ich lerne",
                        item_type="sentence",
                        language="german",
                    ),
                ).props("flat")

    def _build_maintenance_panel(self) -> None:
        with ui.card().classes("w-full"):
            ui.label("Maintenance").classes("text-lg font-semibold")
            ui.label(
                "These actions are local. Build/rebuild commands update local indexes but do not edit notes."
            ).classes("text-sm text-slate-600")

            with ui.grid(columns=2).classes("w-full gap-2 mt-2"):
                ui.button(
                    "Build Language DB",
                    icon="storage",
                    on_click=lambda: self._run_command(self._build_db_spec()),
                ).props("outline")

                ui.button(
                    "Rebuild Relation Index",
                    icon="hub",
                    on_click=lambda: self._run_command(self._rebuild_relations_spec()),
                ).props("outline")

                ui.button(
                    "Schema Validation",
                    icon="fact_check",
                    on_click=lambda: self._run_command(self._schema_validation_spec()),
                ).props("outline")

                ui.button(
                    "Relation Integrity Audit",
                    icon="account_tree",
                    on_click=lambda: self._run_command(self._relation_integrity_spec()),
                ).props("outline")

    def _build_logs_panel(self) -> None:
        with ui.card().classes("w-full"):
            ui.label("Command Output").classes("text-lg font-semibold")
            self.last_command_label = ui.label("No command has been run yet.").classes(
                "text-sm text-slate-500"
            )

            self.output_area = ui.textarea(
                label="Output",
                value="Run an action to see logs here.",
            ).classes("w-full font-mono").props("readonly autogrow")

    def _daily_healthcheck_spec(self, *, skip_build: bool = False) -> CommandSpec:
        args = [
            str(self.runner.python_executable),
            "scripts/daily_healthcheck.py",
        ]

        if skip_build:
            args.append("--skip-build")

        return make_command_spec(
            name="Daily Healthcheck" if not skip_build else "Fast Daily Healthcheck",
            args=args,
            expected_stdout_contains=("Status  : PASS",),
            timeout_seconds=180,
        )

    def _schema_validation_spec(self) -> CommandSpec:
        return make_command_spec(
            name="Schema Validation",
            args=self.runner.python_command(
                "scripts/validate_schema.py",
                "--vault",
                str(self.config.vault_path),
            ),
            expected_stdout_contains=("Errors          : 0",),
            timeout_seconds=120,
        )

    def _build_db_spec(self) -> CommandSpec:
        return make_command_spec(
            name="Build Language DB",
            args=self.runner.python_command("scripts/build_language_db.py"),
            timeout_seconds=120,
        )

    def _rebuild_relations_spec(self) -> CommandSpec:
        return make_command_spec(
            name="Rebuild Relation Index",
            args=self.runner.python_command("scripts/rebuild_relation_index.py"),
            timeout_seconds=120,
        )

    def _key_audit_spec(self) -> CommandSpec:
        return make_command_spec(
            name="Item Key Audit",
            args=self.runner.python_command(
                "scripts/audit_item_keys.py",
                "--vault",
                str(self.config.vault_path),
                "--db",
                str(self.config.db_path),
                "--changed-only",
            ),
            expected_stdout_contains=("Changed records  : 0",),
            timeout_seconds=120,
        )

    def _relation_integrity_spec(self) -> CommandSpec:
        return make_command_spec(
            name="Relation Integrity Audit",
            args=self.runner.python_command(
                "scripts/audit_relation_integrity.py",
                "--db",
                str(self.config.db_path),
                "--vault",
                str(self.config.vault_path),
            ),
            expected_stdout_contains=("Errors          : 0",),
            timeout_seconds=120,
        )

    async def _run_lookup_from_form(self) -> None:
        if self.lookup_query_input is None:
            return

        query = str(self.lookup_query_input.value or "").strip()
        if not query:
            ui.notify("Lookup query cannot be empty.", type="warning")
            return

        item_type = (
            str(self.lookup_type_select.value)
            if self.lookup_type_select is not None
            else "all"
        )
        language = (
            str(self.lookup_language_select.value)
            if self.lookup_language_select is not None
            else "all"
        )
        with_relations = (
            bool(self.lookup_relations_checkbox.value)
            if self.lookup_relations_checkbox is not None
            else True
        )

        await self._run_command(
            self._lookup_spec(
                query=query,
                item_type=item_type,
                language=language,
                with_relations=with_relations,
            )
        )

    async def _run_lookup_preset(
        self,
        *,
        query: str,
        item_type: str,
        language: str,
    ) -> None:
        if self.lookup_query_input is not None:
            self.lookup_query_input.value = query
        if self.lookup_type_select is not None:
            self.lookup_type_select.value = item_type
        if self.lookup_language_select is not None:
            self.lookup_language_select.value = language

        await self._run_command(
            self._lookup_spec(
                query=query,
                item_type=item_type,
                language=language,
                with_relations=True,
            )
        )

    def _lookup_spec(
        self,
        *,
        query: str,
        item_type: str,
        language: str,
        with_relations: bool,
    ) -> CommandSpec:
        args = [
            str(self.runner.python_executable),
            "scripts/lookup_items.py",
            query,
            "--db",
            str(self.config.db_path),
        ]

        if item_type != "all":
            args.extend(["--type", item_type])

        if language != "all":
            args.extend(["--language", language])

        if with_relations:
            args.append("--with-relations")

        return make_command_spec(
            name=f"Lookup: {query}",
            args=args,
            expected_stdout_contains=("LanguageOS Lookup v1",),
            timeout_seconds=120,
        )

    async def _run_command(self, spec: CommandSpec) -> None:
        self._set_output(f"Running: {spec.name}\n\n" + " ".join(spec.args))
        ui.notify(f"Running {spec.name}...", type="info")

        result = await self.runner.run(spec)
        self._apply_result(result)

    def _apply_result(self, result: CommandResult) -> None:
        self._set_output(result.to_display_text())

        if self.last_command_label is not None:
            self.last_command_label.text = f"Last command: {result.name} [{result.status}]"

        if result.name in {"Daily Healthcheck", "Fast Daily Healthcheck"}:
            self._set_status("PASS" if result.passed else "FAIL")
        elif self.status_label is not None and self.status_label.text == "UNKNOWN":
            self._set_status("READY")

        ui.notify(
            f"{result.name}: {result.status}",
            type="positive" if result.passed else "negative",
        )

    def _set_status(self, status: str) -> None:
        if self.status_label is None:
            return

        self.status_label.text = status

        if status == "PASS":
            self.status_label.classes(replace="text-3xl font-bold text-green-600")
        elif status == "FAIL":
            self.status_label.classes(replace="text-3xl font-bold text-red-600")
        elif status == "READY":
            self.status_label.classes(replace="text-3xl font-bold text-blue-600")
        else:
            self.status_label.classes(replace="text-3xl font-bold text-slate-700")

    def _set_output(self, text: str) -> None:
        if self.output_area is not None:
            self.output_area.value = text


def build_arg_parser() -> argparse.ArgumentParser:
    project_root = Path(__file__).resolve().parents[3]

    parser = argparse.ArgumentParser(
        description="Run the local LanguageOS Control Center UI.",
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
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host to bind. Keep 127.0.0.1 for local-only use.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port to serve UI.",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable NiceGUI reload for development.",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Ask NiceGUI to open browser automatically.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    config = LanguageOSUIConfig(
        project_root=args.project_root,
        vault_path=args.vault,
        db_path=args.db,
        host=args.host,
        port=args.port,
    )

    control_center = LanguageOSControlCenter(config)
    control_center.build()

    ui.run(
        host=config.host,
        port=config.port,
        reload=args.reload,
        show=args.show,
        title="LanguageOS Control Center",
    )

    return 0