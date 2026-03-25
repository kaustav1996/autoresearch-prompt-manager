"""ToolSet -- merge external and agent-owned tools safely."""

from __future__ import annotations

from typing import Any, Callable

from shonku.errors import MissingToolError, ToolConflictError
from shonku.types import ToolSpec


def _normalize(item: ToolSpec | Callable[..., Any]) -> ToolSpec:
    """Convert a bare callable into a ToolSpec if needed."""
    if isinstance(item, ToolSpec):
        return item
    if callable(item):
        return ToolSpec(
            name=getattr(item, "__name__", str(item)),
            description=getattr(item, "__doc__", "") or "",
            callable=item,
        )
    raise TypeError(f"Expected ToolSpec or callable, got {type(item)}")


class ToolSet:
    """An ordered, conflict-aware collection of tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    # -- mutators --------------------------------------------------------

    def add(self, tool: ToolSpec | Callable[..., Any]) -> None:
        """Add a tool.  Raises ``ToolConflictError`` on name collision."""
        spec = _normalize(tool)
        if spec.name in self._tools:
            raise ToolConflictError(spec.name)
        self._tools[spec.name] = spec

    def merge(self, other: ToolSet) -> ToolSet:
        """Return a *new* ToolSet containing tools from both sets.

        Raises ``ToolConflictError`` if any names overlap.
        """
        merged = ToolSet()
        for spec in self._tools.values():
            merged.add(spec)
        for spec in other._tools.values():
            merged.add(spec)
        return merged

    # -- queries ---------------------------------------------------------

    def validate_required(self, required: list[str]) -> None:
        """Raise ``MissingToolError`` if any required names are absent."""
        missing = [n for n in required if n not in self._tools]
        if missing:
            raise MissingToolError(missing)

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    # -- conversion to agno ----------------------------------------------

    def to_agno_tools(self) -> list[Callable[..., Any]]:
        """Return a flat list of callables suitable for ``agno.Agent(tools=...)``."""
        return [spec.callable for spec in self._tools.values()]
