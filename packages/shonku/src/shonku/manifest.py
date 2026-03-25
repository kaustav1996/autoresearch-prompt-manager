"""AgentManifest -- metadata for publishing agents as PyPI packages."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgentManifest(BaseModel):
    """Declarative manifest describing a publishable shonku agent.

    This is the metadata that goes into the package so consumers
    can discover and configure the agent without reading source code.
    """

    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    license: str = "MIT"
    agent_class: str = ""  # e.g. "my_package.agents:MyAgent"
    required_tools: list[str] = Field(default_factory=list)
    supported_providers: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    def to_entry_point(self) -> str:
        """Return a console-scripts style entry-point string."""
        return f"shonku.agents.{self.name} = {self.agent_class}"

    def to_pyproject_snippet(self) -> dict:
        """Return a dict suitable for merging into pyproject.toml metadata."""
        return {
            "project": {
                "name": self.name,
                "version": self.version,
                "description": self.description,
                "license": self.license,
                "dependencies": ["shonku>=0.1.0"],
            },
            "project.entry-points": {
                "shonku.agents": {
                    self.name: self.agent_class,
                },
            },
        }
