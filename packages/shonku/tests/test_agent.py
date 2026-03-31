"""Tests for ShonkuAgent and the @tool decorator."""

from __future__ import annotations

from shonku.agent import ShonkuAgent
from shonku.decorators import tool

# -- fixtures ------------------------------------------------------------


class GreeterAgent(ShonkuAgent):
    name = "greeter"
    description = "Says hello"
    instructions = "You greet people."
    required_tools = ["lookup_name"]

    @tool(description="Say hello to someone")
    def greet(self, name: str) -> str:
        return f"Hello, {name}!"

    @tool(name="farewell", description="Say goodbye")
    def say_goodbye(self, name: str) -> str:
        return f"Goodbye, {name}!"


class EmptyAgent(ShonkuAgent):
    name = "empty"


# -- tests ---------------------------------------------------------------


def test_collect_tools_finds_decorated_methods() -> None:
    agent = GreeterAgent()
    names = agent.list_own_tools()
    assert "greet" in names
    assert "farewell" in names
    assert len(names) == 2


def test_tool_spec_has_correct_metadata() -> None:
    agent = GreeterAgent()
    specs = {t.name: t for t in agent._own_tools}

    assert specs["greet"].description == "Say hello to someone"
    assert specs["farewell"].description == "Say goodbye"


def test_tool_callable_works() -> None:
    agent = GreeterAgent()
    specs = {t.name: t for t in agent._own_tools}

    result = specs["greet"].callable("World")
    assert result == "Hello, World!"


def test_empty_agent_has_no_tools() -> None:
    agent = EmptyAgent()
    assert agent.list_own_tools() == []


def test_agent_metadata() -> None:
    agent = GreeterAgent()
    assert agent.name == "greeter"
    assert agent.description == "Says hello"
    assert agent.required_tools == ["lookup_name"]
    assert agent.max_steps == 50


def test_agent_class_decorator() -> None:
    from shonku.decorators import agent as agent_dec

    @agent_dec(name="decorated", description="A decorated agent", version="2.0.0")
    class DecoratedAgent(ShonkuAgent):
        pass

    a = DecoratedAgent()
    assert a.name == "decorated"
    assert a.description == "A decorated agent"
    assert a.version == "2.0.0"
