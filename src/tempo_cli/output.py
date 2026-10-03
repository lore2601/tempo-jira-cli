"""Rendering of results as JSON, NDJSON or human-readable tables.

stdout carries only data; diagnostics and errors go to stderr. JSON output is
stable and intended for programs and agents; tables are for people.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, TextIO

FORMATS = ("auto", "json", "ndjson", "table")

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*(\x07|\x1b\\)")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def resolve_format(fmt: str, stream: TextIO | None = None) -> str:
    if fmt != "auto":
        return fmt
    stream = stream or sys.stdout
    return "table" if stream.isatty() else "json"


def sanitize_terminal(text: str) -> str:
    """Remove escape sequences and control characters (terminal injection)."""
    return _CONTROL_RE.sub("", _ANSI_RE.sub("", text))


def project(item: Any, fields: Sequence[str]) -> Any:
    """Keep only the dotted ``fields`` of ``item`` (``sender.name``, ``text``...)."""
    if not fields or not isinstance(item, dict):
        return item
    result: dict[str, Any] = {}
    for field in fields:
        parts = field.split(".")
        value: Any = item
        for part in parts:
            value = value.get(part) if isinstance(value, dict) else None
        if value is None:
            continue
        target = result
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value
    return result


@dataclass(frozen=True)
class Column:
    header: str
    getter: Callable[[dict[str, Any]], Any]
    max_width: int | None = None


def col(header: str, key: str, max_width: int | None = None) -> Column:
    def getter(item: dict[str, Any]) -> Any:
        value: Any = item
        for part in key.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        return value

    return Column(header, getter, max_width)


def _cell(value: Any, max_width: int | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        text = "yes" if value else ""
    elif isinstance(value, list | dict):
        text = json.dumps(value, ensure_ascii=False) if value else ""
    else:
        text = str(value)
    text = sanitize_terminal(text.replace("\r\n", " ⏎ ").replace("\n", " ⏎ "))
    if max_width and len(text) > max_width:
        text = text[: max_width - 1] + "…"
    return text


def render_table(items: list[dict[str, Any]], columns: Sequence[Column]) -> str:
    if not items:
        return "(no results)"
    term_width = shutil.get_terminal_size((120, 24)).columns
    rows = [[_cell(c.getter(item), c.max_width) for c in columns] for item in items]
    headers = [c.header for c in columns]
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    # Shrink the widest column if the table does not fit the terminal.
    total = sum(widths) + 2 * (len(widths) - 1)
    if total > term_width and widths:
        widest = widths.index(max(widths))
        widths[widest] = max(10, widths[widest] - (total - term_width))
    lines = ["  ".join(h.upper().ljust(w) for h, w in zip(headers, widths, strict=True)).rstrip()]
    for row in rows:
        cells = [
            (c if len(c) <= w else c[: w - 1] + "…").ljust(w)
            for c, w in zip(row, widths, strict=True)
        ]
        lines.append("  ".join(cells).rstrip())
    return "\n".join(lines)


def render_kv(item: dict[str, Any]) -> str:
    if not item:
        return "(empty)"
    width = max(len(k) for k in item)
    lines = []
    for key, value in item.items():
        lines.append(f"{key.ljust(width)}  {_cell(value, None)}")
    return "\n".join(lines)


class Printer:
    """Writes results to stdout in the selected format."""

    def __init__(
        self,
        fmt: str = "auto",
        fields: Sequence[str] = (),
        out: TextIO | None = None,
    ) -> None:
        self.out = out or sys.stdout
        self.fmt = resolve_format(fmt, self.out)
        self.fields = list(fields)

    def _dump(self, data: Any) -> str:
        if self.fmt == "ndjson" or not self.out.isatty():
            return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        return json.dumps(data, ensure_ascii=False, indent=2)

    def _write(self, text: str) -> None:
        self.out.write(text + "\n")
        self.out.flush()

    def item(self, data: dict[str, Any]) -> None:
        data = project(data, self.fields)
        if self.fmt == "table":
            self._write(render_kv(data))
        else:
            self._write(self._dump(data))

    def items(
        self,
        items: list[dict[str, Any]],
        columns: Sequence[Column],
        *,
        next_page_token: str | None = None,
        kind: str = "items",
        extra: dict[str, Any] | None = None,
        more: bool = False,
    ) -> None:
        """Print a list. ``extra`` adds top-level keys to JSON (totals, ranges...)."""
        projected = [project(i, self.fields) for i in items]
        if self.fmt == "json":
            payload: dict[str, Any] = {kind: projected}
            if next_page_token:
                payload["nextPageToken"] = next_page_token
            if more:
                payload["truncated"] = True
            payload.update(extra or {})
            self._write(self._dump(payload))
        elif self.fmt == "ndjson":
            for entry in projected:
                self._write(self._dump(entry))
            if next_page_token:
                info(f"more results available: --page-token {next_page_token}")
            if more:
                info("more results available: raise --limit or use --all")
        else:
            if self.fields:
                columns = [col(f, f, 60) for f in self.fields]
            self._write(render_table(items, columns))
            if next_page_token:
                info(f"more results available: --page-token {next_page_token}")
            if extra:
                info(
                    "  ".join(
                        f"{k}: {v}" for k, v in extra.items() if not isinstance(v, dict | list)
                    )
                )
            if more:
                info("more results available: raise --limit or use --all")


def info(message: str) -> None:
    """Print a diagnostic line to stderr."""
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def print_error(payload: dict[str, Any], fmt: str) -> None:
    if resolve_format(fmt, sys.stderr) == "table":
        err = payload.get("error", {})
        sys.stderr.write(f"error: {err.get('message')}\n")
        if err.get("hint"):
            sys.stderr.write(f"hint: {err['hint']}\n")
    else:
        sys.stderr.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stderr.flush()
