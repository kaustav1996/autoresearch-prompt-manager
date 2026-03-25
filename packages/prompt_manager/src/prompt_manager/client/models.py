"""Client-side response models."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class ResolvedPrompt(BaseModel):
    """The result of resolving a prompt slug."""

    slug: str
    version: int
    body: str
    model_hint: str | None = None
    template_vars: list[str] = Field(default_factory=list)
    content_hash: str
    experiment_id: UUID | None = None
    arm_id: UUID | None = None
    version_id: UUID

    def render(self, **variables: str) -> str:
        """Render the prompt body by replacing ``{{var}}`` placeholders."""
        text = self.body
        for key, value in variables.items():
            text = text.replace("{{" + key + "}}", value)
        return text
