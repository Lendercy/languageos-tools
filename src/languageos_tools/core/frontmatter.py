from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from languageos_tools.core.models import FrontmatterDocument


_FRONTMATTER_DELIMITER = "---"


class FrontmatterError(ValueError):
    pass


class FrontmatterParser:
    def parse(self, text: str) -> FrontmatterDocument:
        if not text.startswith(_FRONTMATTER_DELIMITER):
            return FrontmatterDocument(
                metadata={},
                body=text,
                has_frontmatter=False,
            )

        parts = text.split(_FRONTMATTER_DELIMITER, 2)

        if len(parts) < 3:
            raise FrontmatterError("Invalid frontmatter block: missing closing delimiter.")

        raw_frontmatter = parts[1].strip("\n")
        body = parts[2].lstrip("\n")
        metadata = self._parse_yaml_subset(raw_frontmatter)

        return FrontmatterDocument(
            metadata=metadata,
            body=body,
            has_frontmatter=True,
        )

    def render(self, document: FrontmatterDocument) -> str:
        metadata_text = self.render_metadata(document.metadata)
        body = document.body.lstrip("\n")

        return f"{_FRONTMATTER_DELIMITER}\n{metadata_text}\n{_FRONTMATTER_DELIMITER}\n\n{body}"

    def render_metadata(self, metadata: Mapping[str, Any]) -> str:
        lines: list[str] = []

        for key, value in metadata.items():
            lines.extend(self._render_key_value(key, value))

        return "\n".join(lines).rstrip()

    def _parse_yaml_subset(self, raw_frontmatter: str) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        current_list_key: str | None = None

        for raw_line in raw_frontmatter.splitlines():
            line = raw_line.rstrip()

            if not line.strip():
                continue

            stripped = line.strip()

            if stripped.startswith("- ") and current_list_key:
                item = self._parse_scalar(stripped[2:].strip())
                metadata.setdefault(current_list_key, []).append(item)
                continue

            if ":" not in stripped:
                current_list_key = None
                continue

            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()

            if not key:
                current_list_key = None
                continue

            if value == "":
                metadata[key] = []
                current_list_key = key
            else:
                metadata[key] = self._parse_scalar(value)
                current_list_key = None

        return metadata

    def _parse_scalar(self, value: str) -> Any:
        value = value.strip()

        if value in {"", "null", "None", "~"}:
            return ""

        if value in {"true", "True"}:
            return True

        if value in {"false", "False"}:
            return False

        if value.startswith('"') and value.endswith('"'):
            return value[1:-1]

        if value.startswith("'") and value.endswith("'"):
            return value[1:-1]

        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()

            if not inner:
                return []

            return [
                self._parse_scalar(part.strip())
                for part in inner.split(",")
                if part.strip()
            ]

        return value

    def _render_key_value(self, key: str, value: Any) -> list[str]:
        if isinstance(value, list):
            lines = [f"{key}:"]

            for item in value:
                lines.append(f"  - {self._render_scalar(item)}")

            return lines

        return [f"{key}: {self._render_scalar(value)}"]

    def _render_scalar(self, value: Any) -> str:
        if value is None:
            return ""

        if isinstance(value, bool):
            return "true" if value else "false"

        text = str(value)

        if text == "":
            return ""

        if self._needs_quotes(text):
            escaped = text.replace('"', '\\"')
            return f'"{escaped}"'

        return text

    def _needs_quotes(self, value: str) -> bool:
        if value.strip() != value:
            return True

        if value.lower() in {"true", "false", "null", "none", "~"}:
            return True

        if value.startswith(("[", "{", "-", "*", "&", "!", "#", "@")):
            return True

        if re.search(r":\s", value):
            return True

        return False


def parse_frontmatter(text: str) -> FrontmatterDocument:
    return FrontmatterParser().parse(text)


def render_frontmatter(document: FrontmatterDocument) -> str:
    return FrontmatterParser().render(document)