"""Decorators for building shonku agents and tools."""

from __future__ import annotations

from typing import Callable, TypeVar

F = TypeVar("F", bound=Callable)


def tool(name: str | None = None, description: str = "") -> Callable[[F], F]:
    """Mark a method on a ShonkuAgent subclass as a tool.

    Parameters
    ----------
    name:
        Override the tool name. Defaults to the function name.
    description:
        Human-readable description. Falls back to the function docstring.
    """

    def decorator(func: F) -> F:
        func._shonku_tool = True  # type: ignore[attr-defined]
        func._shonku_tool_name = name or func.__name__  # type: ignore[attr-defined]
        func._shonku_tool_description = (  # type: ignore[attr-defined]
            description or func.__doc__ or ""
        )
        return func

    return decorator


def agent(
    name: str | None = None,
    description: str = "",
    version: str = "0.1.0",
    instructions: str = "",
) -> Callable[[type], type]:
    """Class decorator that sets agent metadata on a ShonkuAgent subclass."""

    def decorator(cls: type) -> type:
        if name is not None:
            cls.name = name  # type: ignore[attr-defined]
        if description:
            cls.description = description  # type: ignore[attr-defined]
        if version:
            cls.version = version  # type: ignore[attr-defined]
        if instructions:
            cls.instructions = instructions  # type: ignore[attr-defined]
        return cls

    return decorator
