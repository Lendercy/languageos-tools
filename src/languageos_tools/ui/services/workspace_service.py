from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from languageos_tools.datastore.relation_repository import (
    RelationRepository,
    RelationRepositoryConfig,
)
from languageos_tools.search.lookup_service import LookupMatch, LookupService


@dataclass(frozen=True)
class WorkspaceItemView:
    item_key: str
    item_type: str
    language: str
    normalized: str
    title: str
    file_path: str
    text_preview: str
    match_kind: str
    score: float

    def to_json_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class WorkspaceRelationView:
    direction: str
    relation_type: str
    source_key: str
    target_key: str
    connected_key: str
    connected_label: str
    connected_path: str
    evidence: str
    confidence: float

    def to_json_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class WorkspaceLookupView:
    query: str
    db_path: str
    items: tuple[WorkspaceItemView, ...]
    selected_item: WorkspaceItemView | None
    outgoing_relations: tuple[WorkspaceRelationView, ...]
    incoming_relations: tuple[WorkspaceRelationView, ...]

    @property
    def has_matches(self) -> bool:
        return bool(self.items)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "db_path": self.db_path,
            "items": [item.to_json_dict() for item in self.items],
            "selected_item": (
                self.selected_item.to_json_dict() if self.selected_item else None
            ),
            "outgoing_relations": [
                relation.to_json_dict() for relation in self.outgoing_relations
            ],
            "incoming_relations": [
                relation.to_json_dict() for relation in self.incoming_relations
            ],
        }


class WorkspaceService:
    """
    Service layer for the Learner Workspace UI.

    Responsibilities:
    - Search/lookup LanguageOS items from the SQLite index.
    - Build UI-friendly item view models.
    - Load incoming/outgoing relations for the selected item.
    - Keep UI code free from direct SQL and repository details.
    """

    def __init__(self, *, db_path: Path) -> None:
        self.db_path = db_path
        self.lookup_service = LookupService(db_path=db_path)
        self.relation_repository = RelationRepository(
            RelationRepositoryConfig(db_path=db_path)
        )

    def lookup(
        self,
        *,
        query: str,
        item_type: str | None = None,
        language: str | None = None,
        limit: int = 20,
        selected_item_key: str | None = None,
    ) -> WorkspaceLookupView:
        clean_query = query.strip()

        if not clean_query:
            return WorkspaceLookupView(
                query=query,
                db_path=str(self.db_path),
                items=(),
                selected_item=None,
                outgoing_relations=(),
                incoming_relations=(),
            )

        report = self.lookup_service.lookup(
            query=clean_query,
            item_type=item_type,
            language=language,
            limit=limit,
            with_relations=False,
        )

        items = tuple(self._to_item_view(match) for match in report.matches)
        selected_item = self._select_item(
            items=items,
            selected_item_key=selected_item_key,
        )

        outgoing: tuple[WorkspaceRelationView, ...] = ()
        incoming: tuple[WorkspaceRelationView, ...] = ()

        if selected_item is not None:
            neighbors = self.relation_repository.get_neighbors(
                selected_item.item_key,
            )
            outgoing = tuple(
                self._to_relation_view(row=row, direction="outgoing")
                for row in neighbors["outgoing"]
            )
            incoming = tuple(
                self._to_relation_view(row=row, direction="incoming")
                for row in neighbors["incoming"]
            )

        return WorkspaceLookupView(
            query=clean_query,
            db_path=str(self.db_path),
            items=items,
            selected_item=selected_item,
            outgoing_relations=outgoing,
            incoming_relations=incoming,
        )

    def _select_item(
        self,
        *,
        items: tuple[WorkspaceItemView, ...],
        selected_item_key: str | None,
    ) -> WorkspaceItemView | None:
        if not items:
            return None

        if selected_item_key:
            for item in items:
                if item.item_key == selected_item_key:
                    return item

        return items[0]

    def _to_item_view(self, match: LookupMatch) -> WorkspaceItemView:
        item = match.item

        title = item.title or self._display_from_item_key(item.item_key)
        file_path = item.file_path or ""
        text_preview = item.text_preview or ""

        return WorkspaceItemView(
            item_key=item.item_key,
            item_type=item.item_type,
            language=item.language,
            normalized=item.normalized,
            title=title,
            file_path=file_path,
            text_preview=text_preview,
            match_kind=match.match_kind.value,
            score=match.score,
        )

    def _to_relation_view(
        self,
        *,
        row: dict,
        direction: str,
    ) -> WorkspaceRelationView:
        source_key = str(row["source_key"])
        target_key = str(row["target_key"])

        if direction == "outgoing":
            connected_key = target_key
            connected_path = str(row.get("target_path") or "")
        else:
            connected_key = source_key
            connected_path = str(row.get("source_path") or "")

        return WorkspaceRelationView(
            direction=direction,
            relation_type=str(row["relation_type"]),
            source_key=source_key,
            target_key=target_key,
            connected_key=connected_key,
            connected_label=self._display_from_item_key(connected_key),
            connected_path=connected_path,
            evidence=str(row.get("evidence") or ""),
            confidence=float(row.get("confidence") or 0.0),
        )

    def _display_from_item_key(self, item_key: str) -> str:
        parts = item_key.split("|", 2)

        if len(parts) != 3:
            return item_key

        return parts[2].strip() or item_key