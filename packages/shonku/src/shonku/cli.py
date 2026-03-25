"""shonku CLI — scaffold and manage agent projects.

Usage:
    shonku init [name]       Scaffold a new agent project
    shonku list              List agents in current project
    shonku run <agent>       Run an agent
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

AGENT_TEMPLATE = '''"""TODO: Describe your agent."""

from __future__ import annotations

import json

from shonku import ShonkuAgent, tool


class {class_name}(ShonkuAgent):
    """{description}"""

    name = "{agent_name}"
    description = "{description}"
    version = "0.1.0"
    instructions = (
        "You are a helpful agent. Use the tools provided to accomplish tasks.\\n"
        "Be concise and accurate."
    )

    # Tools the caller MUST provide at runtime
    required_tools = []

    @tool(description="Example built-in tool")
    def hello(self, name: str) -> str:
        """Say hello to someone."""
        return json.dumps({{"message": f"Hello, {{name}}!"}})
'''

PYPROJECT_TEMPLATE = '''[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "{package_name}"
version = "0.1.0"
description = "{description}"
readme = "README.md"
license = "MIT"
requires-python = ">=3.10"
dependencies = [
    "shonku>=0.1.0",
    "pydantic>=2.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23"]

[tool.hatch.build.targets.wheel]
packages = ["src/{module_name}"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
'''

README_TEMPLATE = '''# {package_name}

{description}

Built with [shonku](https://github.com/kaustav1996/autoresearch-prompt-manager).

## Install

```bash
pip install {package_name}
```

## Usage

```python
from {module_name} import {class_name}
from shonku import LLMConfig

agent = {class_name}()
result = await agent.run(
    input="Your task here",
    llm_config=LLMConfig(provider="groq", model="llama-3.3-70b-versatile", api_key="..."),
    tools=[],  # pass external tools here
)
print(result.content)
```

## Development

```bash
pip install -e ".[dev]"
pytest
```
'''

TEST_TEMPLATE = '''"""Tests for {class_name}."""

from {module_name} import {class_name}


class TestAgent:
    def test_metadata(self) -> None:
        agent = {class_name}()
        assert agent.name == "{agent_name}"

    def test_own_tools(self) -> None:
        agent = {class_name}()
        tool_names = [t.name for t in agent._own_tools]
        assert "hello" in tool_names
'''

INIT_TEMPLATE = '''"""{package_name} — {description}"""

from {module_name}.agent import {class_name}

__all__ = ["{class_name}"]
'''


def _to_class_name(name: str) -> str:
    """Convert 'my-cool-agent' to 'MyCoolAgent'."""
    return "".join(word.capitalize() for word in name.replace("_", "-").split("-")) + "Agent"


def _to_module_name(name: str) -> str:
    """Convert 'my-cool-agent' to 'my_cool_agent'."""
    return name.replace("-", "_")


def cmd_init(args: argparse.Namespace) -> None:
    """Scaffold a new shonku agent project."""
    name = args.name
    if not name:
        name = input("Agent project name (e.g. my-agent): ").strip()
    if not name:
        print("Error: name is required")
        sys.exit(1)

    module_name = _to_module_name(name)
    class_name = _to_class_name(name)
    description = args.description or f"A shonku agent: {name}"

    root = Path.cwd() / name if not args.here else Path.cwd()
    if not args.here:
        root.mkdir(parents=True, exist_ok=True)

    src = root / "src" / module_name
    tests = root / "tests"
    src.mkdir(parents=True, exist_ok=True)
    tests.mkdir(parents=True, exist_ok=True)

    ctx = {
        "package_name": name,
        "module_name": module_name,
        "class_name": class_name,
        "agent_name": name,
        "description": description,
    }

    # Write files
    (src / "__init__.py").write_text(INIT_TEMPLATE.format(**ctx))
    (src / "agent.py").write_text(AGENT_TEMPLATE.format(**ctx))
    (tests / "__init__.py").write_text("")
    (tests / "test_agent.py").write_text(TEST_TEMPLATE.format(**ctx))
    (root / "pyproject.toml").write_text(PYPROJECT_TEMPLATE.format(**ctx))
    (root / "README.md").write_text(README_TEMPLATE.format(**ctx))

    print(f"Scaffolded shonku agent project: {name}")
    print(f"  {root}/")
    print(f"    src/{module_name}/agent.py    <- your agent")
    print("    tests/test_agent.py           <- tests")
    print("    pyproject.toml                <- package config")
    print("    README.md")
    print()
    print("Next steps:")
    print(f"  cd {name}")
    print("  pip install -e '.[dev]'")
    print("  pytest")
    print()
    print(f"Edit src/{module_name}/agent.py to build your agent.")


def cmd_list(args: argparse.Namespace) -> None:
    """List agents found in the current project."""
    src = Path.cwd() / "src"
    if not src.exists():
        print("No src/ directory found. Run 'shonku init' first.")
        return
    for f in src.rglob("*.py"):
        text = f.read_text()
        if "ShonkuAgent" in text and "class " in text:
            print(f"  {f.relative_to(Path.cwd())}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="shonku",
        description="Build, publish, and run AI agents",
    )
    sub = parser.add_subparsers(dest="command")

    init_p = sub.add_parser("init", help="Scaffold a new agent project")
    init_p.add_argument("name", nargs="?", help="Project name")
    init_p.add_argument("-d", "--description", help="Agent description")
    init_p.add_argument(
        "--here", action="store_true",
        help="Scaffold in current directory instead of creating a subdirectory",
    )

    sub.add_parser("list", help="List agents in current project")

    args = parser.parse_args()

    if args.command == "init":
        cmd_init(args)
    elif args.command == "list":
        cmd_list(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
