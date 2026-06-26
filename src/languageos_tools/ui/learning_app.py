from __future__ import annotations

import argparse
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

        with ui.column().classes("w-full max-w-6xl mx-auto p-4 gap-4"):
            self._build_summary_cards()
            self._build_filters()
            self._build_study_area()

        self.reload_deck()

    def _build_summary_cards(self) -> None:
        with ui.grid(columns=3).classes("w-full gap-4"):
            with ui.card().classes("w-full"):
                ui.label("Deck").classes("text-sm text-slate-500")
                self.deck_count_label = ui.label("0 cards").classes(
                    "text-3xl font-bold text-purple-700"
                )

            with ui.card().classes("w-full"):
                ui.label("Progress").classes("text-sm text-slate-500")
                self.progress_label = ui.label("0 / 0").classes(
                    "text-3xl font-bold text-slate-700"
                )

            with ui.card().classes("w-full"):
                ui.label("Session").classes("text-sm text-slate-500")
                self.stats_label = ui.label("Again 0 · Good 0 · Easy 0").classes(
                    "text-lg font-semibold text-slate-700"
                )

    def _build_filters(self) -> None:
        with ui.card().classes("w-full"):
            ui.label("Study Filters").classes("text-lg font-semibold")

            with ui.row().classes("w-full gap-3 items-end"):
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
                    "Reset Session",
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

    def _render_current_card(self) -> None:
        if self.card_container is None:
            return

        self.card_container.clear()

        with self.card_container:
            if not self.cards:
                with ui.card().classes("w-full p-8 text-center"):
                    ui.icon("school").classes("text-6xl text-slate-300")
                    ui.label("No study cards found.").classes(
                        "text-xl font-semibold text-slate-600"
                    )
                    ui.label(
                        "Try changing filters or adding vocabulary/sentence/grammar notes."
                    ).classes("text-sm text-slate-500")
                return

            card = self.cards[self.current_index]

            with ui.card().classes("w-full p-6"):
                with ui.row().classes("w-full justify-between items-center"):
                    ui.label(card.note_type.upper()).classes(
                        "text-xs font-bold bg-purple-100 text-purple-700 px-2 py-1 rounded"
                    )
                    ui.label(card.language).classes(
                        "text-xs font-semibold bg-slate-100 text-slate-700 px-2 py-1 rounded"
                    )

                ui.label(card.front).classes(
                    "text-4xl font-bold text-center my-8 text-slate-900"
                )

                ui.label(card.item_key).classes(
                    "text-xs font-mono text-slate-400 text-center"
                )

                with ui.row().classes("w-full justify-center gap-2 mt-4"):
                    ui.button(
                        "Previous",
                        icon="chevron_left",
                        on_click=self.previous_card,
                    ).props("outline")

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

            if self.answer_revealed:
                self._render_answer(card)
                self._render_rating_buttons()

    def _render_answer(self, card: StudyCard) -> None:
        with ui.card().classes("w-full p-6 bg-slate-50"):
            ui.label("Meaning / Explanation").classes(
                "text-lg font-semibold text-slate-800"
            )
            ui.markdown(card.back).classes("text-base text-slate-800")

            if card.examples:
                ui.separator()
                ui.label("Examples").classes("text-lg font-semibold text-slate-800")
                ui.markdown(card.examples).classes("text-base text-slate-800")

            if card.notes:
                ui.separator()
                ui.label("Notes").classes("text-lg font-semibold text-slate-800")
                ui.markdown(card.notes).classes("text-base text-slate-800")

            if card.relations:
                ui.separator()
                ui.label("Relations").classes("text-lg font-semibold text-slate-800")
                for relation in card.relations:
                    if relation.direction == "outgoing":
                        text = (
                            f"→ **{relation.relation_type}** → "
                            f"`{relation.target_key}`"
                        )
                    else:
                        text = (
                            f"← **{relation.relation_type}** ← "
                            f"`{relation.source_key}`"
                        )
                    ui.markdown(text).classes("text-sm")

            ui.separator()
            ui.label(f"File: {card.file_path}").classes(
                "text-xs font-mono text-slate-500 break-all"
            )

    def _render_rating_buttons(self) -> None:
        with ui.card().classes("w-full"):
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