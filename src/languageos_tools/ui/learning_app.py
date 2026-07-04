from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from nicegui import ui

from languageos_tools.integrations.external_apps import (
    ExternalAppConfig,
    ExternalAppService,
)
from languageos_tools.study.study_service import (
    StudyCard,
    StudyFilter,
    StudyService,
)
from languageos_tools.ui.services.maintenance_service import (
    MaintenanceCommandResult,
    MaintenanceService,
    WorkspaceHealthReport,
)
from languageos_tools.ui.services.workspace_service import (
    WorkspaceItemView,
    WorkspaceLookupView,
    WorkspaceRelationView,
    WorkspaceService,
)


@dataclass(frozen=True)
class LearningUIConfig:
    vault_path: Path
    db_path: Path
    local_apps_config_path: Path
    project_root: Path
    host: str = "127.0.0.1"
    port: int = 8082


@dataclass(frozen=True)
class NavigationPage:
    key: str
    title: str
    subtitle: str
    icon: str


class LanguageOSLearningApp:
    """
    Learner-facing UI for LanguageOS.

    This version uses a fixed app-shell layout:
    - top header
    - collapsible fixed left sidebar navigation
    - one active content window on the right
    """

    PAGES: tuple[NavigationPage, ...] = (
        NavigationPage(
            key="dashboard",
            title="Dashboard",
            subtitle="Overview of your local learning system.",
            icon="dashboard",
        ),
        NavigationPage(
            key="workspace",
            title="Workspace",
            subtitle="Search, inspect, and connect learning items.",
            icon="travel_explore",
        ),
        NavigationPage(
            key="review",
            title="Review",
            subtitle="Study cards from your LanguageOS vault.",
            icon="school",
        ),
        NavigationPage(
            key="maintenance",
            title="Maintenance",
            subtitle="Healthcheck and safe rebuild actions.",
            icon="construction",
        ),
        NavigationPage(
            key="settings",
            title="Settings",
            subtitle="Local paths and runtime configuration.",
            icon="settings",
        ),
    )

    def __init__(self, config: LearningUIConfig) -> None:
        self.config = config

        self.study_service = StudyService(
            vault_path=config.vault_path,
            db_path=config.db_path,
        )
        self.workspace_service = WorkspaceService(
            db_path=config.db_path,
        )
        self.maintenance_service = MaintenanceService(
            project_root=config.project_root,
            db_path=config.db_path,
        )
        self.external_apps = ExternalAppService(
            ExternalAppConfig.load(
                vault_path=config.vault_path,
                config_path=config.local_apps_config_path,
            )
        )

        self.active_page = "dashboard"
        self.sidebar_collapsed = False

        self.sidebar_container: ui.column | None = None
        self.main_container: ui.column | None = None

        self.cards: list[StudyCard] = []
        self.current_index = 0
        self.answer_revealed = False

        self.again_count = 0
        self.good_count = 0
        self.easy_count = 0

        self.deck_count_label: ui.label | None = None
        self.progress_label: ui.label | None = None
        self.stats_label: ui.label | None = None
        self.dashboard_health_label: ui.label | None = None

        self.language_select: ui.select | None = None
        self.type_select: ui.select | None = None
        self.query_input: ui.input | None = None
        self.card_container: ui.column | None = None

        self.workspace_query_input: ui.input | None = None
        self.workspace_language_select: ui.select | None = None
        self.workspace_type_select: ui.select | None = None
        self.workspace_results_container: ui.column | None = None
        self.workspace_inspector_container: ui.column | None = None
        self.workspace_last_view: WorkspaceLookupView | None = None

        self.health_container: ui.column | None = None
        self.maintenance_output_container: ui.column | None = None
        self.last_health_report: WorkspaceHealthReport | None = None

    def build(self) -> None:
        ui.colors(
            primary="#7c3aed",
            secondary="#475569",
            accent="#14b8a6",
            positive="#16a34a",
            negative="#dc2626",
            warning="#f59e0b",
        )

        ui.page_title("LanguageOS Learner Workspace")
        self._add_layout_css()
        self._build_app_shell()

        self.reload_deck(show_notification=False)
        self.run_healthcheck(show_notification=False)
        self.search_workspace(show_notification=False)

    def _add_layout_css(self) -> None:
        ui.add_head_html(
            """
            <style>
                body {
                    background: #f8fafc;
                }

                .los-app-shell {
                    min-height: 100vh;
                    width: 100%;
                    background: #f8fafc;
                }

                .los-header {
                    height: 56px;
                    width: 100%;
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    padding: 0 20px;
                    background: #0f172a;
                    color: white;
                    border-bottom: 1px solid #1e293b;
                }

                .los-body {
                    display: flex;
                    width: 100%;
                    min-height: calc(100vh - 56px);
                }

                .los-sidebar {
                    width: 268px;
                    min-width: 268px;
                    min-height: calc(100vh - 56px);
                    background: #111827;
                    color: white;
                    border-right: 1px solid #1f2937;
                    padding: 16px 12px;
                    transition: width 180ms ease, min-width 180ms ease, padding 180ms ease;
                }

                .los-sidebar-collapsed {
                    width: 76px;
                    min-width: 76px;
                    padding: 16px 8px;
                }

                .los-sidebar-collapsed .los-sidebar-text {
                    display: none;
                }

                .los-sidebar-collapsed .los-sidebar-section {
                    display: none;
                }

                .los-sidebar-collapsed .los-nav-button {
                    justify-content: center;
                    padding-left: 0;
                    padding-right: 0;
                }

                .los-sidebar-collapsed .q-btn__content {
                    justify-content: center;
                }

                .los-collapse-button {
                    width: 100%;
                    justify-content: flex-end;
                    margin-bottom: 12px;
                    border-radius: 10px;
                }

                .los-sidebar-collapsed .los-collapse-button {
                    justify-content: center;
                }

                .los-main {
                    flex: 1;
                    min-width: 0;
                    min-height: calc(100vh - 56px);
                    padding: 24px;
                    background: #f8fafc;
                }

                .los-page-window {
                    width: 100%;
                    max-width: 1280px;
                    margin: 0 auto;
                }

                .los-nav-button {
                    width: 100%;
                    justify-content: flex-start;
                    border-radius: 10px;
                    margin-bottom: 4px;
                }

                .los-card {
                    background: white;
                    border: 1px solid #e5e7eb;
                    border-radius: 14px;
                    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
                }
            </style>
            """
        )

    def _build_app_shell(self) -> None:
        with ui.element("div").classes("los-app-shell"):
            self._build_header()

            with ui.element("div").classes("los-body"):
                self.sidebar_container = ui.column().classes(self._sidebar_classes())
                self._render_sidebar()

                self.main_container = ui.column().classes("los-main")
                self._render_active_page()

    def _build_header(self) -> None:
        with ui.element("div").classes("los-header"):
            with ui.row().classes("items-center gap-3"):
                ui.icon("language").classes("text-2xl text-purple-300")
                with ui.column().classes("gap-0"):
                    ui.label("LanguageOS").classes("text-base font-bold")
                    ui.label("Learner Workspace").classes("text-xs text-slate-300")

            ui.label("Local-first English / German").classes(
                "text-xs bg-purple-100 text-purple-800 px-3 py-1 rounded-full"
            )

    def toggle_sidebar(self) -> None:
        self.sidebar_collapsed = not self.sidebar_collapsed

        if self.sidebar_container is not None:
            self.sidebar_container.classes(replace=self._sidebar_classes())

        self._render_sidebar()

    def _sidebar_classes(self) -> str:
        base_classes = "los-sidebar gap-2"
        if self.sidebar_collapsed:
            return f"{base_classes} los-sidebar-collapsed"

        return base_classes

    def _render_sidebar(self) -> None:
        if self.sidebar_container is None:
            return

        self.sidebar_container.clear()

        with self.sidebar_container:
            collapse_icon = "chevron_right" if self.sidebar_collapsed else "chevron_left"
            collapse_label = "" if self.sidebar_collapsed else "Collapse"

            ui.button(
                collapse_label,
                icon=collapse_icon,
                on_click=self.toggle_sidebar,
            ).props("flat no-caps").classes("los-collapse-button text-slate-300")

            if not self.sidebar_collapsed:
                ui.label("Navigation").classes(
                    "los-sidebar-section text-xs uppercase tracking-wide text-slate-400 px-2 mt-1 mb-2"
                )

            for page in self.PAGES:
                is_active = self.active_page == page.key
                classes = (
                    "los-nav-button "
                    + (
                        "bg-purple-600 text-white"
                        if is_active
                        else "text-slate-200 hover:bg-slate-800"
                    )
                )

                label = "" if self.sidebar_collapsed else page.title

                button = (
                    ui.button(
                        label,
                        icon=page.icon,
                        on_click=lambda page_key=page.key: self.show_page(page_key),
                    )
                    .props("flat no-caps align=left")
                    .classes(classes)
                )
                button.tooltip(page.title)

            if not self.sidebar_collapsed:
                ui.separator().classes("my-4 bg-slate-700")

                ui.label("System Rules").classes(
                    "los-sidebar-section text-xs uppercase tracking-wide text-slate-400 px-2 mb-1"
                )
                ui.label(
                    "Local-first. No auto-delete, auto-merge, or auto-Anki export."
                ).classes(
                    "los-sidebar-section text-xs text-slate-400 px-2 leading-relaxed"
                )

                ui.separator().classes("my-4 bg-slate-700")

                ui.label("Current Branch").classes(
                    "los-sidebar-section text-xs uppercase tracking-wide text-slate-400 px-2 mb-1"
                )
                ui.label("learner-workspace-ui-v4").classes(
                    "los-sidebar-section text-xs font-mono text-slate-300 px-2"
                )

    def show_page(self, page_key: str) -> None:
        self.active_page = page_key
        self._render_sidebar()
        self._render_active_page()

    def _render_active_page(self) -> None:
        if self.main_container is None:
            return

        self.main_container.clear()
        page = self._current_page_definition()

        with self.main_container:
            with ui.column().classes("los-page-window gap-4"):
                with ui.row().classes("w-full justify-between items-start"):
                    with ui.column().classes("gap-1"):
                        ui.label(page.title).classes(
                            "text-3xl font-bold text-slate-900"
                        )
                        ui.label(page.subtitle).classes("text-sm text-slate-500")

                    ui.button(
                        "Refresh Health",
                        icon="refresh",
                        on_click=self.run_healthcheck,
                    ).props("outline").classes("bg-white")

                if page.key == "dashboard":
                    self._render_dashboard_page()
                elif page.key == "workspace":
                    self._render_workspace_page()
                elif page.key == "review":
                    self._render_review_page()
                elif page.key == "maintenance":
                    self._render_maintenance_page()
                elif page.key == "settings":
                    self._render_settings_page()

    def _render_dashboard_page(self) -> None:
        self._render_summary_cards()

        with ui.grid(columns=2).classes("w-full gap-4"):
            with ui.card().classes("los-card w-full p-5"):
                ui.label("System Status").classes("text-lg font-semibold")
                self.dashboard_health_label = ui.label(
                    self._dashboard_health_text()
                ).classes("text-sm text-slate-600 mt-2")

                with ui.row().classes("gap-2 mt-4"):
                    ui.button(
                        "Open Maintenance",
                        icon="construction",
                        on_click=lambda: self.show_page("maintenance"),
                    ).props("unelevated")
                    ui.button(
                        "Run Healthcheck",
                        icon="health_and_safety",
                        on_click=self.run_healthcheck,
                    ).props("outline")

            with ui.card().classes("los-card w-full p-5"):
                ui.label("Quick Actions").classes("text-lg font-semibold")
                ui.label("Jump to a focused workspace.").classes(
                    "text-sm text-slate-500 mt-2"
                )

                with ui.row().classes("gap-2 mt-4"):
                    ui.button(
                        "Workspace",
                        icon="travel_explore",
                        on_click=lambda: self.show_page("workspace"),
                    ).props("outline")
                    ui.button(
                        "Review",
                        icon="school",
                        on_click=lambda: self.show_page("review"),
                    ).props("outline")
                    ui.button(
                        "Settings",
                        icon="settings",
                        on_click=lambda: self.show_page("settings"),
                    ).props("outline")

    def _render_summary_cards(self) -> None:
        with ui.grid(columns=3).classes("w-full gap-4"):
            with ui.card().classes("los-card w-full p-5"):
                ui.label("Deck").classes("text-sm text-slate-500")
                self.deck_count_label = ui.label(f"{len(self.cards)} cards").classes(
                    "text-3xl font-bold text-purple-700"
                )

            with ui.card().classes("los-card w-full p-5"):
                ui.label("Progress").classes("text-sm text-slate-500")
                self.progress_label = ui.label(self._progress_text()).classes(
                    "text-3xl font-bold text-slate-800"
                )

            with ui.card().classes("los-card w-full p-5"):
                ui.label("Session").classes("text-sm text-slate-500")
                self.stats_label = ui.label(self._session_stats_text()).classes(
                    "text-lg font-semibold text-slate-700"
                )

    def _render_workspace_page(self) -> None:
        with ui.card().classes("los-card w-full p-5"):
            with ui.row().classes("w-full gap-3 items-end"):
                self.workspace_language_select = ui.select(
                    label="Language",
                    options=["all", "german", "english"],
                    value=self._select_value(
                        self.workspace_language_select,
                        default="german",
                    ),
                ).classes("w-44")

                self.workspace_type_select = ui.select(
                    label="Type",
                    options=["all", "vocabulary", "sentence", "grammar"],
                    value=self._select_value(self.workspace_type_select, default="all"),
                ).classes("w-44")

                self.workspace_query_input = ui.input(
                    label="Search item",
                    placeholder="trotzdem / Contrast connectors / Ich lerne",
                    value=self._workspace_query_value(),
                    on_change=lambda _: self.search_workspace(),
                ).classes("grow")

                ui.button(
                    "Search",
                    icon="search",
                    on_click=self.search_workspace,
                ).props("unelevated")

                ui.button(
                    "Clear",
                    icon="clear",
                    on_click=self.clear_workspace,
                ).props("outline")

        with ui.grid(columns=2).classes("w-full gap-4"):
            self.workspace_results_container = ui.column().classes("w-full gap-2")
            self.workspace_inspector_container = ui.column().classes("w-full gap-2")

        self._render_workspace()

    def _render_review_page(self) -> None:
        with ui.card().classes("los-card w-full p-5"):
            with ui.row().classes("w-full gap-3 items-end"):
                self.language_select = ui.select(
                    label="Language",
                    options=["all", "german", "english"],
                    value=self._select_value(self.language_select, default="german"),
                ).classes("w-48")

                self.type_select = ui.select(
                    label="Type",
                    options=["all", "vocabulary", "sentence", "grammar"],
                    value=self._select_value(self.type_select, default="all"),
                ).classes("w-48")

                self.query_input = ui.input(
                    label="Search",
                    placeholder="trotzdem / contrast / ich lerne",
                    value=str(self.query_input.value or "") if self.query_input else "",
                ).classes("grow")

                ui.button(
                    "Load Deck",
                    icon="refresh",
                    on_click=self.reload_deck,
                ).props("unelevated")

                ui.button(
                    "Reset",
                    icon="restart_alt",
                    on_click=self.reset_session,
                ).props("outline")

                ui.button(
                    "Check Anki",
                    icon="sync",
                    on_click=self.check_anki_connect,
                ).props("outline")

                ui.button(
                    "Open Anki",
                    icon="style",
                    on_click=self.open_anki_app,
                ).props("outline")

        self.card_container = ui.column().classes("w-full gap-4")
        self._render_current_card()

    def _render_maintenance_page(self) -> None:
        with ui.card().classes("los-card w-full p-5"):
            ui.label("Maintenance Actions").classes("text-lg font-semibold")
            ui.label(
                "Actions are explicit and safe. Use dry-run first when unsure."
            ).classes("text-sm text-slate-500 mt-1")

            with ui.row().classes("w-full gap-2 mt-4"):
                ui.button(
                    "Healthcheck",
                    icon="health_and_safety",
                    on_click=self.run_healthcheck,
                ).props("unelevated")

                ui.button(
                    "Dry-run Build DB",
                    icon="visibility",
                    on_click=lambda: self.run_build_database(dry_run=True),
                ).props("outline")

                ui.button(
                    "Build DB",
                    icon="storage",
                    on_click=lambda: self.run_build_database(dry_run=False),
                ).props("outline color=warning")

                ui.button(
                    "Dry-run Relations",
                    icon="visibility",
                    on_click=lambda: self.run_rebuild_relation_index(dry_run=True),
                ).props("outline")

                ui.button(
                    "Rebuild Relations",
                    icon="hub",
                    on_click=lambda: self.run_rebuild_relation_index(dry_run=False),
                ).props("outline color=warning")

        with ui.grid(columns=2).classes("w-full gap-4"):
            self.health_container = ui.column().classes("w-full gap-2")
            self.maintenance_output_container = ui.column().classes("w-full gap-2")

        if self.last_health_report is not None:
            self._render_health_report(self.last_health_report)

    def _render_settings_page(self) -> None:
        with ui.card().classes("los-card w-full p-5"):
            ui.label("Local Configuration").classes("text-lg font-semibold")
            ui.label(
                "These paths define your local-first LanguageOS runtime."
            ).classes("text-sm text-slate-500 mt-1")

            ui.separator().classes("my-4")

            self._render_setting_row("Project root", str(self.config.project_root))
            self._render_setting_row("Vault path", str(self.config.vault_path))
            self._render_setting_row("Database path", str(self.config.db_path))
            self._render_setting_row(
                "Local apps config",
                str(self.config.local_apps_config_path),
            )
            self._render_setting_row("Host", self.config.host)
            self._render_setting_row("Port", str(self.config.port))

    def _render_setting_row(self, label: str, value: str) -> None:
        with ui.row().classes("w-full items-start gap-4 py-2 border-b border-slate-100"):
            ui.label(label).classes("w-40 text-sm font-semibold text-slate-700")
            ui.label(value).classes("text-sm font-mono text-slate-500 break-all")

    def search_workspace(self, *, show_notification: bool = True) -> None:
        query = self._workspace_query_value()
        language = self._select_value(self.workspace_language_select, default="german")
        item_type = self._select_value(self.workspace_type_select, default="all")

        language_filter = None if language == "all" else language
        type_filter = None if item_type == "all" else item_type

        try:
            self.workspace_last_view = self.workspace_service.lookup(
                query=query,
                language=language_filter,
                item_type=type_filter,
                limit=20,
            )
        except Exception as exc:
            ui.notify(f"Workspace lookup failed: {exc}", type="negative")
            self.workspace_last_view = None

        self._render_workspace()

        if show_notification and query:
            ui.notify("Workspace search updated.", type="positive")

    def clear_workspace(self) -> None:
        if self.workspace_query_input is not None:
            self.workspace_query_input.value = ""

        self.workspace_last_view = None
        self._render_workspace()

    def select_workspace_item(self, item_key: str) -> None:
        if self.workspace_last_view is None:
            return

        try:
            self.workspace_last_view = self.workspace_service.lookup(
                query=self.workspace_last_view.query,
                language=self._workspace_language_filter(),
                item_type=self._workspace_type_filter(),
                limit=20,
                selected_item_key=item_key,
            )
        except Exception as exc:
            ui.notify(f"Could not select item: {exc}", type="negative")
            return

        self._render_workspace()

    def run_healthcheck(self, *, show_notification: bool = True) -> None:
        try:
            self.last_health_report = self.maintenance_service.healthcheck()
        except Exception as exc:
            ui.notify(f"Healthcheck failed: {exc}", type="negative")
            return

        self._render_health_report(self.last_health_report)
        self._update_dashboard_health()

        if show_notification:
            ui.notify(
                "Healthcheck completed.",
                type="positive" if self.last_health_report.ok else "warning",
            )

    def run_build_database(self, *, dry_run: bool) -> None:
        result = self.maintenance_service.build_database(dry_run=dry_run)
        self._render_maintenance_command_result(result)

        ui.notify(
            result.message,
            type="positive" if result.success else "negative",
            timeout=5000,
        )

        if result.success and not dry_run:
            self.run_healthcheck(show_notification=False)
            self.reload_deck(show_notification=False)
            self.search_workspace(show_notification=False)

    def run_rebuild_relation_index(self, *, dry_run: bool) -> None:
        result = self.maintenance_service.rebuild_relation_index(dry_run=dry_run)
        self._render_maintenance_command_result(result)

        ui.notify(
            result.message,
            type="positive" if result.success else "negative",
            timeout=5000,
        )

        if result.success and not dry_run:
            self.run_healthcheck(show_notification=False)
            self.search_workspace(show_notification=False)

    def copy_workspace_note_path(self) -> None:
        item = self._selected_workspace_item()
        if item is None or not item.file_path:
            ui.notify("No workspace note path available.", type="warning")
            return

        ui.clipboard.write(item.file_path)
        ui.notify("Copied workspace note path.", type="positive")

    def copy_workspace_obsidian_uri(self) -> None:
        item = self._selected_workspace_item()
        if item is None or not item.file_path:
            ui.notify("No workspace note path available.", type="warning")
            return

        try:
            uri = self.external_apps.build_obsidian_uri(item.file_path)
        except Exception as exc:
            ui.notify(f"Could not build Obsidian URI: {exc}", type="negative")
            return

        ui.clipboard.write(uri)
        ui.notify("Copied workspace Obsidian URI.", type="positive")

    def open_workspace_note(self) -> None:
        item = self._selected_workspace_item()
        if item is None or not item.file_path:
            ui.notify("No workspace note path available.", type="warning")
            return

        result = self.external_apps.open_obsidian_note(item.file_path)
        ui.notify(
            result.message,
            type="positive" if result.success else "negative",
        )

    def reload_deck(self, *, show_notification: bool = True) -> None:
        language = self._select_value(self.language_select, default="german")
        note_type = self._select_value(self.type_select, default="all")
        query = str(self.query_input.value or "") if self.query_input else ""

        deck = self.study_service.load_deck(
            StudyFilter(
                language=language,
                note_type=note_type,
                query=query,
                limit=200,
            )
        )

        self.cards = list(deck.cards)
        self.current_index = 0
        self.answer_revealed = False

        self._update_summary()
        self._render_current_card()

        if show_notification:
            ui.notify(f"Loaded {len(self.cards)} study cards.", type="positive")

    def reset_session(self) -> None:
        self.again_count = 0
        self.good_count = 0
        self.easy_count = 0
        self.current_index = 0
        self.answer_revealed = False

        self._update_summary()
        self._render_current_card()

        ui.notify("Session reset.", type="info")

    def reveal_answer(self) -> None:
        self.answer_revealed = True
        self._render_current_card()

    def hide_answer(self) -> None:
        self.answer_revealed = False
        self._render_current_card()

    def rate_card(self, rating: str) -> None:
        if not self.cards:
            return

        if rating == "again":
            self.again_count += 1
        elif rating == "good":
            self.good_count += 1
        elif rating == "easy":
            self.easy_count += 1

        if self.current_index < len(self.cards) - 1:
            self.current_index += 1
        else:
            ui.notify("Deck finished.", type="positive")

        self.answer_revealed = False

        self._update_summary()
        self._render_current_card()

    def previous_card(self) -> None:
        if not self.cards:
            return

        self.current_index = max(0, self.current_index - 1)
        self.answer_revealed = False

        self._update_summary()
        self._render_current_card()

    def next_card(self) -> None:
        if not self.cards:
            return

        self.current_index = min(len(self.cards) - 1, self.current_index + 1)
        self.answer_revealed = False

        self._update_summary()
        self._render_current_card()

    def copy_current_note_path(self) -> None:
        card = self._current_card()
        if card is None:
            return

        ui.clipboard.write(card.file_path)
        ui.notify("Copied file path.", type="positive")

    def copy_current_obsidian_uri(self) -> None:
        card = self._current_card()
        if card is None:
            return

        try:
            uri = self.external_apps.build_obsidian_uri(card.file_path)
        except Exception as exc:
            ui.notify(f"Could not build Obsidian URI: {exc}", type="negative")
            return

        ui.clipboard.write(uri)
        ui.notify("Copied Obsidian URI.", type="positive")

    def open_current_note(self) -> None:
        card = self._current_card()
        if card is None:
            return

        result = self.external_apps.open_obsidian_note(card.file_path)
        ui.notify(
            result.message,
            type="positive" if result.success else "negative",
        )

    def open_anki_app(self) -> None:
        result = self.external_apps.open_anki_app()
        ui.notify(
            result.message,
            type="positive" if result.success else "negative",
        )

    def check_anki_connect(self) -> None:
        status = self.external_apps.check_anki_connect()
        ui.notify(
            status.message,
            type="positive" if status.online else "warning",
            timeout=5000,
        )

    def _render_workspace(self) -> None:
        if self.workspace_results_container is None:
            return
        if self.workspace_inspector_container is None:
            return

        self.workspace_results_container.clear()
        self.workspace_inspector_container.clear()

        with self.workspace_results_container:
            self._render_workspace_results()

        with self.workspace_inspector_container:
            self._render_workspace_inspector()

    def _render_workspace_results(self) -> None:
        view = self.workspace_last_view

        with ui.card().classes("los-card w-full p-4"):
            ui.label("Search Results").classes("text-base font-semibold text-slate-800")

            if view is None or not view.query:
                ui.label("Enter a query to inspect LanguageOS items.").classes(
                    "text-sm text-slate-500"
                )
                return

            if not view.items:
                ui.label("No matching items found.").classes("text-sm text-slate-500")
                return

            ui.label(f"{len(view.items)} match(es)").classes("text-xs text-slate-500")

            for item in view.items:
                self._render_workspace_result_item(item)

    def _render_workspace_result_item(self, item: WorkspaceItemView) -> None:
        selected = (
            self.workspace_last_view is not None
            and self.workspace_last_view.selected_item is not None
            and self.workspace_last_view.selected_item.item_key == item.item_key
        )

        border_class = "border-purple-300 bg-purple-50" if selected else "bg-white"

        card = ui.card().classes(
            f"w-full p-3 cursor-pointer shadow-none border {border_class}"
        )
        card.on(
            "click",
            lambda _, item_key=item.item_key: self.select_workspace_item(item_key),
        )

        with card:
            with ui.row().classes("w-full justify-between items-center"):
                ui.label(item.title).classes("text-sm font-semibold text-slate-800")
                ui.label(f"{item.score:.2f}").classes(
                    "text-xs font-mono text-slate-400"
                )

            with ui.row().classes("gap-2"):
                ui.label(item.item_type.upper()).classes(
                    "text-[10px] font-bold bg-purple-100 text-purple-700 px-2 py-1 rounded"
                )
                ui.label(item.language).classes(
                    "text-[10px] font-semibold bg-slate-100 text-slate-700 px-2 py-1 rounded"
                )
                ui.label(item.match_kind).classes(
                    "text-[10px] font-semibold bg-teal-100 text-teal-700 px-2 py-1 rounded"
                )

            ui.label(item.item_key).classes(
                "text-xs font-mono text-slate-400 break-all"
            )

    def _render_workspace_inspector(self) -> None:
        view = self.workspace_last_view

        with ui.card().classes("los-card w-full p-4"):
            ui.label("Item Inspector").classes("text-base font-semibold text-slate-800")

            if view is None or view.selected_item is None:
                ui.label("Select a search result to inspect it.").classes(
                    "text-sm text-slate-500"
                )
                return

            item = view.selected_item

            with ui.row().classes("gap-2 mt-2"):
                ui.label(item.item_type.upper()).classes(
                    "text-xs font-bold bg-purple-100 text-purple-700 px-2 py-1 rounded"
                )
                ui.label(item.language).classes(
                    "text-xs font-semibold bg-slate-100 text-slate-700 px-2 py-1 rounded"
                )

            ui.label(item.title).classes(
                "text-3xl font-bold text-slate-900 leading-tight mt-3"
            )

            ui.label(item.item_key).classes(
                "text-xs font-mono text-slate-400 break-all mt-1"
            )

            if item.text_preview:
                ui.separator()
                ui.label("Preview").classes("text-sm font-semibold text-slate-700")
                ui.label(item.text_preview).classes(
                    "text-sm text-slate-700 leading-relaxed"
                )

            if item.file_path:
                ui.separator()
                ui.label("Obsidian Path").classes(
                    "text-sm font-semibold text-slate-700"
                )
                ui.label(item.file_path).classes(
                    "text-xs font-mono text-slate-500 break-all"
                )

                with ui.row().classes("gap-2"):
                    ui.button(
                        "Copy Path",
                        icon="content_copy",
                        on_click=self.copy_workspace_note_path,
                    ).props("flat size=sm")

                    ui.button(
                        "Copy URI",
                        icon="link",
                        on_click=self.copy_workspace_obsidian_uri,
                    ).props("flat size=sm")

                    ui.button(
                        "Open Obsidian",
                        icon="open_in_new",
                        on_click=self.open_workspace_note,
                    ).props("flat size=sm")

            ui.separator()
            self._render_workspace_relation_section(
                title="Outgoing Relations",
                relations=view.outgoing_relations,
            )

            ui.separator()
            self._render_workspace_relation_section(
                title="Incoming Relations",
                relations=view.incoming_relations,
            )

    def _render_workspace_relation_section(
        self,
        *,
        title: str,
        relations: tuple[WorkspaceRelationView, ...],
    ) -> None:
        ui.label(title).classes("text-sm font-semibold text-slate-700")

        if not relations:
            ui.label("No relations found.").classes("text-xs text-slate-500")
            return

        for relation in relations:
            with ui.row().classes(
                "w-full items-center gap-2 bg-slate-50 border border-slate-200 rounded p-2"
            ):
                icon = "arrow_forward" if relation.direction == "outgoing" else "reply"
                ui.icon(icon).classes("text-purple-500")
                ui.label(self._relation_label(relation.relation_type)).classes(
                    "text-xs font-semibold text-slate-500 w-36"
                )
                ui.label(relation.connected_label).classes(
                    "text-sm font-medium text-slate-800"
                )
                ui.label(f"{relation.confidence:.2f}").classes(
                    "text-xs font-mono text-slate-400 ml-auto"
                )

    def _render_health_report(self, report: WorkspaceHealthReport) -> None:
        if self.health_container is None:
            return

        self.health_container.clear()

        with self.health_container:
            status_icon = "check_circle" if report.ok else "warning"
            status_class = "text-green-600" if report.ok else "text-amber-600"
            status_text = "Healthy" if report.ok else "Needs attention"

            with ui.card().classes("los-card w-full p-4"):
                with ui.row().classes("w-full items-center gap-2"):
                    ui.icon(status_icon).classes(f"text-2xl {status_class}")
                    ui.label(status_text).classes(f"text-lg font-bold {status_class}")

                ui.label(f"Checked at: {report.checked_at:%Y-%m-%d %H:%M:%S}").classes(
                    "text-xs text-slate-500"
                )

                ui.separator()

                with ui.grid(columns=2).classes("w-full gap-2"):
                    self._render_health_metric(
                        label="DB Exists",
                        value="yes" if report.db_exists else "no",
                    )
                    self._render_health_metric(
                        label="DB Size",
                        value=f"{report.db_size_bytes:,} bytes",
                    )
                    self._render_health_metric(
                        label="Language Items",
                        value=self._optional_int(report.language_item_count),
                    )
                    self._render_health_metric(
                        label="Relations",
                        value=self._optional_int(report.relation_count),
                    )

                ui.separator()
                ui.label("Checks").classes("text-sm font-semibold text-slate-700")

                for check in report.checks:
                    icon = "check_circle" if check.ok else "error"
                    color = "text-green-600" if check.ok else "text-red-600"

                    with ui.row().classes(
                        "w-full items-start gap-2 bg-slate-50 border border-slate-200 rounded p-2"
                    ):
                        ui.icon(icon).classes(color)
                        with ui.column().classes("gap-0"):
                            ui.label(check.name).classes(
                                "text-xs font-bold text-slate-600"
                            )
                            ui.label(check.message).classes("text-xs text-slate-500")

    def _render_health_metric(self, *, label: str, value: str) -> None:
        with ui.card().classes("p-3 shadow-none bg-slate-50 border border-slate-200"):
            ui.label(label).classes("text-xs text-slate-500")
            ui.label(value).classes("text-lg font-bold text-slate-800")

    def _render_maintenance_command_result(
        self,
        result: MaintenanceCommandResult,
    ) -> None:
        if self.maintenance_output_container is None:
            return

        self.maintenance_output_container.clear()

        with self.maintenance_output_container:
            status_icon = "check_circle" if result.success else "error"
            status_class = "text-green-600" if result.success else "text-red-600"

            with ui.card().classes("los-card w-full p-4"):
                with ui.row().classes("w-full items-center gap-2"):
                    ui.icon(status_icon).classes(f"text-2xl {status_class}")
                    ui.label(result.message).classes(
                        f"text-lg font-bold {status_class}"
                    )

                ui.label(f"Command: {' '.join(result.command)}").classes(
                    "text-xs font-mono text-slate-500 break-all"
                )

                if result.returncode is not None:
                    ui.label(f"Return code: {result.returncode}").classes(
                        "text-xs font-mono text-slate-500"
                    )

                if result.stdout:
                    ui.separator()
                    ui.label("STDOUT").classes("text-xs font-bold text-slate-600")
                    ui.code(result.stdout).classes("w-full text-xs")

                if result.stderr:
                    ui.separator()
                    ui.label("STDERR").classes("text-xs font-bold text-red-600")
                    ui.code(result.stderr).classes("w-full text-xs")

    def _render_current_card(self) -> None:
        if self.card_container is None:
            return

        self.card_container.clear()

        with self.card_container:
            if not self.cards:
                self._render_empty_state()
                return

            card = self.cards[self.current_index]

            if self.answer_revealed:
                with ui.grid(columns=2).classes("w-full gap-4"):
                    self._render_front_card(card, compact=True)
                    self._render_answer_panel(card)

                self._render_rating_buttons()
            else:
                self._render_front_card(card, compact=False)

    def _render_empty_state(self) -> None:
        with ui.card().classes("los-card w-full p-8 text-center"):
            ui.icon("school").classes("text-6xl text-slate-300")
            ui.label("No study cards found.").classes(
                "text-xl font-semibold text-slate-600"
            )
            ui.label(
                "Try changing filters or adding vocabulary, sentence, or grammar notes."
            ).classes("text-sm text-slate-500")

    def _render_front_card(self, card: StudyCard, *, compact: bool) -> None:
        card_class = "los-card w-full p-6"
        if not compact:
            card_class = "los-card w-full p-8"

        with ui.card().classes(card_class):
            with ui.row().classes("w-full justify-between items-center"):
                with ui.row().classes("gap-2"):
                    ui.label(card.note_type.upper()).classes(
                        "text-xs font-bold bg-purple-100 text-purple-700 px-2 py-1 rounded"
                    )
                    ui.label(card.language).classes(
                        "text-xs font-semibold bg-slate-100 text-slate-700 px-2 py-1 rounded"
                    )

                ui.label(f"{self.current_index + 1} / {len(self.cards)}").classes(
                    "text-xs font-mono text-slate-400"
                )

            ui.label(card.subtitle).classes("text-sm text-slate-500 text-center mt-4")

            front_size = "text-3xl" if compact else "text-5xl"
            ui.label(card.front).classes(
                f"{front_size} font-bold text-center my-8 text-slate-900 leading-tight"
            )

            ui.label(card.item_key).classes(
                "text-xs font-mono text-slate-400 text-center break-all"
            )

            with ui.row().classes("w-full justify-center gap-2 mt-6"):
                ui.button(
                    "Previous",
                    icon="chevron_left",
                    on_click=self.previous_card,
                ).props("outline")

                if self.answer_revealed:
                    ui.button(
                        "Hide",
                        icon="visibility_off",
                        on_click=self.hide_answer,
                    ).props("outline")
                else:
                    ui.button(
                        "Show Meaning",
                        icon="visibility",
                        on_click=self.reveal_answer,
                    ).props("unelevated")

                ui.button(
                    "Next",
                    icon="chevron_right",
                    on_click=self.next_card,
                ).props("outline")

            with ui.row().classes("w-full justify-center gap-2 mt-3"):
                ui.button(
                    "Copy Path",
                    icon="content_copy",
                    on_click=self.copy_current_note_path,
                ).props("flat size=sm")

                ui.button(
                    "Copy Obsidian URI",
                    icon="link",
                    on_click=self.copy_current_obsidian_uri,
                ).props("flat size=sm")

                ui.button(
                    "Open Obsidian",
                    icon="open_in_new",
                    on_click=self.open_current_note,
                ).props("flat size=sm")

    def _render_answer_panel(self, card: StudyCard) -> None:
        with ui.card().classes("los-card w-full p-6"):
            ui.label("Meaning / Explanation").classes(
                "text-lg font-semibold text-slate-800"
            )
            ui.markdown(card.back).classes("text-base text-slate-800 leading-relaxed")

            if card.examples:
                ui.separator()
                ui.label("Examples").classes("text-base font-semibold text-slate-800")
                ui.markdown(card.examples).classes(
                    "text-sm text-slate-800 leading-relaxed"
                )

            if card.notes:
                ui.separator()
                ui.label("Notes").classes("text-base font-semibold text-slate-800")
                ui.markdown(card.notes).classes(
                    "text-sm text-slate-800 leading-relaxed"
                )

            if card.relations:
                ui.separator()
                ui.label("Connected Notes").classes(
                    "text-base font-semibold text-slate-800"
                )

                for relation in card.relations:
                    self._render_relation_chip(
                        relation.display_label,
                        relation.display_item,
                    )

            ui.separator()
            ui.label(card.file_path).classes(
                "text-xs font-mono text-slate-500 break-all"
            )

    def _render_relation_chip(self, label: str, item: str) -> None:
        with ui.row().classes(
            "w-full items-center gap-2 bg-slate-50 border border-slate-200 rounded p-2"
        ):
            ui.icon("hub").classes("text-purple-500")
            ui.label(label).classes("text-xs font-semibold text-slate-500 w-36")
            ui.label(item).classes("text-sm font-medium text-slate-800")

    def _render_rating_buttons(self) -> None:
        with ui.card().classes("los-card w-full"):
            with ui.row().classes("w-full justify-between items-center"):
                ui.label("How well did you remember this?").classes(
                    "text-sm font-semibold text-slate-600"
                )

                with ui.row().classes("gap-2"):
                    ui.button(
                        "Again",
                        icon="replay",
                        on_click=lambda: self.rate_card("again"),
                    ).props("color=negative outline")

                    ui.button(
                        "Good",
                        icon="thumb_up",
                        on_click=lambda: self.rate_card("good"),
                    ).props("color=positive unelevated")

                    ui.button(
                        "Easy",
                        icon="star",
                        on_click=lambda: self.rate_card("easy"),
                    ).props("color=primary unelevated")

    def _update_summary(self) -> None:
        if self.deck_count_label is not None:
            self.deck_count_label.text = f"{len(self.cards)} cards"

        if self.progress_label is not None:
            self.progress_label.text = self._progress_text()

        if self.stats_label is not None:
            self.stats_label.text = self._session_stats_text()

    def _update_dashboard_health(self) -> None:
        if self.dashboard_health_label is not None:
            self.dashboard_health_label.text = self._dashboard_health_text()

    def _current_page_definition(self) -> NavigationPage:
        for page in self.PAGES:
            if page.key == self.active_page:
                return page
        return self.PAGES[0]

    def _select_value(self, select: ui.select | None, *, default: str) -> str:
        if select is None:
            return default

        value = str(select.value or default).strip().casefold()
        return value or default

    def _current_card(self) -> StudyCard | None:
        if not self.cards:
            return None

        if self.current_index < 0 or self.current_index >= len(self.cards):
            return None

        return self.cards[self.current_index]

    def _workspace_language_filter(self) -> str | None:
        language = self._select_value(self.workspace_language_select, default="german")
        return None if language == "all" else language

    def _workspace_type_filter(self) -> str | None:
        item_type = self._select_value(self.workspace_type_select, default="all")
        return None if item_type == "all" else item_type

    def _selected_workspace_item(self) -> WorkspaceItemView | None:
        if self.workspace_last_view is None:
            return None

        return self.workspace_last_view.selected_item

    def _workspace_query_value(self) -> str:
        if self.workspace_query_input is None:
            return "trotzdem"

        return str(self.workspace_query_input.value or "").strip()

    def _relation_label(self, relation_type: str) -> str:
        return relation_type.replace("_", " ").title()

    def _optional_int(self, value: int | None) -> str:
        if value is None:
            return "unknown"

        return f"{value:,}"

    def _progress_text(self) -> str:
        if not self.cards:
            return "0 / 0"

        return f"{self.current_index + 1} / {len(self.cards)}"

    def _session_stats_text(self) -> str:
        return (
            f"Again {self.again_count} • "
            f"Good {self.good_count} • "
            f"Easy {self.easy_count}"
        )

    def _dashboard_health_text(self) -> str:
        if self.last_health_report is None:
            return "Healthcheck has not run yet."

        if self.last_health_report.ok:
            return "System is healthy."

        return "System needs attention. Open Maintenance for details."


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the LanguageOS learner-facing study UI.",
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
        "--local-apps-config",
        type=Path,
        default=Path("configs/local_apps.json"),
        help="Local external app config path.",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project root path.",
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
        default=8082,
        help="Port to serve learner UI.",
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
    args = build_arg_parser().parse_args(argv)

    app = LanguageOSLearningApp(
        LearningUIConfig(
            vault_path=args.vault,
            db_path=args.db,
            local_apps_config_path=args.local_apps_config,
            project_root=args.project_root.resolve(),
            host=args.host,
            port=args.port,
        )
    )
    app.build()

    ui.run(
        host=args.host,
        port=args.port,
        reload=args.reload,
        show=args.show,
        title="LanguageOS Learner Workspace",
    )

    return 0