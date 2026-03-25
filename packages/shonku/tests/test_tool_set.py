"""Tests for ToolSet merging, conflict detection, and validation."""

from __future__ import annotations

import pytest

from shonku.errors import MissingToolError, ToolConflictError
from shonku.tool_set import ToolSet
from shonku.types import ToolSpec


# -- helpers -------------------------------------------------------------


def _make_spec(name: str) -> ToolSpec:
    return ToolSpec(name=name, description=f"{name} tool", callable=lambda: name)


def _dummy_fn() -> str:
    """A dummy function."""
    return "ok"


# -- tests ---------------------------------------------------------------


class TestAdd:
    def test_add_tool_spec(self) -> None:
        ts = ToolSet()
        ts.add(_make_spec("alpha"))
        assert "alpha" in ts
        assert len(ts) == 1

    def test_add_bare_callable(self) -> None:
        ts = ToolSet()
        ts.add(_dummy_fn)
        assert "_dummy_fn" in ts

    def test_add_conflict_raises(self) -> None:
        ts = ToolSet()
        ts.add(_make_spec("alpha"))
        with pytest.raises(ToolConflictError) as exc_info:
            ts.add(_make_spec("alpha"))
        assert exc_info.value.tool_name == "alpha"

    def test_add_non_callable_raises(self) -> None:
        ts = ToolSet()
        with pytest.raises(TypeError):
            ts.add(42)  # type: ignore[arg-type]


class TestMerge:
    def test_merge_disjoint(self) -> None:
        a = ToolSet()
        a.add(_make_spec("one"))
        b = ToolSet()
        b.add(_make_spec("two"))

        merged = a.merge(b)
        assert len(merged) == 2
        assert "one" in merged
        assert "two" in merged

    def test_merge_conflict_raises(self) -> None:
        a = ToolSet()
        a.add(_make_spec("shared"))
        b = ToolSet()
        b.add(_make_spec("shared"))

        with pytest.raises(ToolConflictError):
            a.merge(b)

    def test_merge_returns_new_instance(self) -> None:
        a = ToolSet()
        a.add(_make_spec("x"))
        b = ToolSet()
        merged = a.merge(b)
        assert merged is not a
        assert merged is not b


class TestValidateRequired:
    def test_all_present(self) -> None:
        ts = ToolSet()
        ts.add(_make_spec("search"))
        ts.add(_make_spec("fetch"))
        ts.validate_required(["search", "fetch"])  # should not raise

    def test_missing_raises(self) -> None:
        ts = ToolSet()
        ts.add(_make_spec("search"))
        with pytest.raises(MissingToolError) as exc_info:
            ts.validate_required(["search", "fetch", "save"])
        assert set(exc_info.value.missing_tools) == {"fetch", "save"}

    def test_empty_required(self) -> None:
        ts = ToolSet()
        ts.validate_required([])  # should not raise


class TestToAgnoTools:
    def test_returns_callables(self) -> None:
        ts = ToolSet()
        ts.add(_make_spec("a"))
        ts.add(_dummy_fn)
        agno_tools = ts.to_agno_tools()
        assert len(agno_tools) == 2
        assert all(callable(t) for t in agno_tools)

    def test_names_order(self) -> None:
        ts = ToolSet()
        ts.add(_make_spec("beta"))
        ts.add(_make_spec("alpha"))
        assert ts.names() == ["beta", "alpha"]
