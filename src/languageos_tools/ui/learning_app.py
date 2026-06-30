from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from nicegui import ui

from languageos_tools.study.study_service import (
    StudyCard,
    StudyFilter,
    StudyService,
)


@dataclass(frozen=True)
class LearningUIConfig:
    vault_path: Path
    db_path: Path
    host: str = "127.0.0.1"
    port: int = 8082


class LanguageOSLearningApp:
    """
    Learner-facing UI for LanguageOS.

    This is separate from the admin Control Center. It focuses on studying:
    vocabulary, sentences, grammar, meanings/explanations, examples, and relations.
    """

    def __init__(self, config: LearningUIConfig) -> None:
        self.config = config
        self.study_service = StudyService(
            vault_path=config.vault_path,
            db_path=config.db_path,
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

    def build(self) -> None:
        ui.colors(
            primary="#7c3aed",
            secondary="#475569",
            accent="#14b8a6",
            positive="#16a34a",
            negative="#dc2626",
            warning="#f59e0b",
        )

        ui.page_title("LanguageOS Learner")

        with ui.header().classes("items-center justify-between bg-purple-700"):
            ui.label("LanguageOS Learner").classes("text-xl font-bold tracking-wide")
            ui.label("English / German").classes(
                "text-xs uppercase bg-white text-purple-700 px-2 py-1 rounded"
            )

        with ui.column().classes("w-full max-w-7xl mx-auto p-4 gap-4"):
            self._build_summary_cards()
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
                self.stats_label = ui.label("Again 0 · Good 0 · Easy 0").classes(
                    "text-lg font-semibold text-slate-700"
                )

    def _build_filters(self) -> None:
        with ui.card().classes("w-full shadow-sm"):
            with ui.row().classes("w-full justify-between items-center"):
                with ui.column().classes("gap-0"):
                    ui.label("Study Filters").classes("text-lg font-semibold")
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

    def _build_study_area(self) -> None:
        self.card_container = ui.column().classes("w-full gap-4")

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
        ui.notify("Copied note path.", type="positive")

    def open_current_note(self) -> None:
        card = self._current_card()
        if card is None:
            return

        try:
            os.startfile(card.file_path)  # type: ignore[attr-defined]
            ui.notify("Opening note.", type="positive")
        except Exception as exc:
            ui.notify(f"Could not open note: {exc}", type="negative")

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
                    "Open Note",
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
                    self._render_relation_chip(relation.display_label, relation.display_item)

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
                self.progress_label.text = f"{self.current_index + 1} / {len(self.cards)}"
            else:
                self.progress_label.text = "0 / 0"

        if self.stats_label is not None:
            self.stats_label.text = (
                f"Again {self.again_count} · "
                f"Good {self.good_count} · "
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
        title="LanguageOS Learner",
    )

    return 0