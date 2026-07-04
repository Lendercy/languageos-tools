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
    host: str = "127.0.0.1"
    port: int = 8082


class LanguageOSLearningApp:
    """
    Learner-facing UI for LanguageOS.

    This app has two learner-focused modes:
    - Workspace mode: search, inspect items, and browse relations.
    - Review mode: study vocabulary, sentence, and grammar cards.
    """

    def __init__(self, config: LearningUIConfig) -> None:
        self.config = config

        self.study_service = StudyService(
            vault_path=config.vault_path,
            db_path=config.db_path,
        )
        self.workspace_service = WorkspaceService(
            db_path=config.db_path,
        )

        self.external_apps = ExternalAppService(
            ExternalAppConfig.load(
                vault_path=config.vault_path,
                config_path=config.local_apps_config_path,
            )
        )

        self.cards: list[StudyCard] = []
        self.current_index = 0
        self.answer_revealed = False

        self.again_count = 0
        self.good_count = 0
        self.easy_count = 0

        self.deck_count_label: ui.label | None = None
        self.progress_label: ui.label | None = None
        self.stats_label: ui.label | None = None
        self.card_container: ui.column | None = None

        self.language_select: ui.select | None = None
        self.type_select: ui.select | None = None
        self.query_input: ui.input | None = None

        self.workspace_query_input: ui.input | None = None
        self.workspace_language_select: ui.select | None = None
        self.workspace_type_select: ui.select | None = None
        self.workspace_results_container: ui.column | None = None
        self.workspace_inspector_container: ui.column | None = None
        self.workspace_last_view: WorkspaceLookupView | None = None

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

        with ui.header().classes("items-center justify-between bg-purple-700"):
            with ui.row().classes("items-center gap-3"):
                ui.icon("school").classes("text-2xl")
                ui.label("LanguageOS Learner Workspace").classes(
                    "text-xl font-bold tracking-wide"
                )

            ui.label("English / German").classes(
                "text-xs uppercase bg-white text-purple-700 px-2 py-1 rounded"
            )

        with ui.column().classes("w-full max-w-7xl mx-auto p-4 gap-4"):
            self._build_summary_cards()
            self._build_workspace_area()
            self._build_filters()
            self._build_study_area()

        self.reload_deck()

    def _build_summary_cards(self) -> None:
        with ui.grid(columns=3).classes("w-full gap-4"):
            with ui.card().classes("w-full shadow-sm"):
                ui.label("Deck").classes("text-sm text-slate-500")
                self.deck_count_label = ui.label("0 cards").classes(
                    "text-3xl font-bold text-purple-700"
                )

            with ui.card().classes("w-full shadow-sm"):
                ui.label("Progress").classes("text-sm text-slate-500")
                self.progress_label = ui.label("0 / 0").classes(
                    "text-3xl font-bold text-slate-700"
                )

            with ui.card().classes("w-full shadow-sm"):
                ui.label("Session").classes("text-sm text-slate-500")
                self.stats_label = ui.label("Again 0 • Good 0 • Easy 0").classes(
                    "text-lg font-semibold text-slate-700"
                )

    def _build_workspace_area(self) -> None:
        with ui.card().classes("w-full shadow-sm"):
            with ui.row().classes("w-full justify-between items-center"):
                with ui.column().classes("gap-0"):
                    ui.label("Workspace Inspector").classes("text-lg font-semibold")
                    ui.label(
                        "Search an item, inspect metadata, and browse relations."
                    ).classes("text-sm text-slate-500")

            with ui.row().classes("w-full gap-3 items-end mt-2"):
                self.workspace_language_select = ui.select(
                    label="Language",
                    options=["all", "german", "english"],
                    value="german",
                ).classes("w-44")

                self.workspace_type_select = ui.select(
                    label="Type",
                    options=["all", "vocabulary", "sentence", "grammar"],
                    value="all",
                ).classes("w-44")

                self.workspace_query_input = ui.input(
                    label="Search item",
                    placeholder="trotzdem / Contrast connectors / Ich lerne",
                    value="trotzdem",
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

            with ui.grid(columns=2).classes("w-full gap-4 mt-4"):
                self.workspace_results_container = ui.column().classes("w-full gap-2")
                self.workspace_inspector_container = ui.column().classes(
                    "w-full gap-2"
                )

        self.search_workspace()

    def _build_filters(self) -> None:
        with ui.card().classes("w-full shadow-sm"):
            with ui.row().classes("w-full justify-between items-center"):
                with ui.column().classes("gap-0"):
                    ui.label("Review Deck").classes("text-lg font-semibold")
                    ui.label("Choose what you want to review now.").classes(
                        "text-sm text-slate-500"
                    )

            with ui.row().classes("w-full gap-3 items-end mt-2"):
                self.language_select = ui.select(
                    label="Language",
                    options=["all", "german", "english"],
                    value="german",
                ).classes("w-48")

                self.type_select = ui.select(
                    label="Type",
                    options=["all", "vocabulary", "sentence", "grammar"],
                    value="all",
                ).classes("w-48")

                self.query_input = ui.input(
                    label="Search",
                    placeholder="trotzdem / contrast / ich lerne",
                    value="",
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

    def _build_study_area(self) -> None:
        self.card_container = ui.column().classes("w-full gap-4")

    def search_workspace(self) -> None:
        query = str(self.workspace_query_input.value or "").strip()
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

        with ui.card().classes("w-full p-4 bg-slate-50 shadow-none"):
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
        card.on("click", lambda _, item_key=item.item_key: self.select_workspace_item(item_key))

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

        with ui.card().classes("w-full p-4 bg-slate-50 shadow-none"):
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
                "w-full items-center gap-2 bg-white border border-slate-200 rounded p-2"
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

    def reload_deck(self) -> None:
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
        with ui.card().classes("w-full p-8 text-center shadow-sm"):
            ui.icon("school").classes("text-6xl text-slate-300")
            ui.label("No study cards found.").classes(
                "text-xl font-semibold text-slate-600"
            )
            ui.label(
                "Try changing filters or adding vocabulary, sentence, or grammar notes."
            ).classes("text-sm text-slate-500")

    def _render_front_card(self, card: StudyCard, *, compact: bool) -> None:
        card_class = "w-full p-6 shadow-sm"
        if not compact:
            card_class = "w-full p-8 shadow-sm"

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
        with ui.card().classes("w-full p-6 bg-slate-50 shadow-sm"):
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
            "w-full items-center gap-2 bg-white border border-slate-200 rounded p-2"
        ):
            ui.icon("hub").classes("text-purple-500")
            ui.label(label).classes("text-xs font-semibold text-slate-500 w-36")
            ui.label(item).classes("text-sm font-medium text-slate-800")

    def _render_rating_buttons(self) -> None:
        with ui.card().classes("w-full shadow-sm"):
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
            if self.cards:
                self.progress_label.text = (
                    f"{self.current_index + 1} / {len(self.cards)}"
                )
            else:
                self.progress_label.text = "0 / 0"

        if self.stats_label is not None:
            self.stats_label.text = (
                f"Again {self.again_count} • "
                f"Good {self.good_count} • "
                f"Easy {self.easy_count}"
            )

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

    def _relation_label(self, relation_type: str) -> str:
        return relation_type.replace("_", " ").title()


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