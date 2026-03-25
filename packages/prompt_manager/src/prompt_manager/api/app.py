"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from prompt_manager.api.db.engine import close_pool, create_pool, run_migrations
from prompt_manager.api.routers import experiments, metrics, optimize, prompts, resolve, versions
from prompt_manager.core.config import PromptManagerSettings


def create_app(settings: PromptManagerSettings | None = None) -> FastAPI:
    """Build and return the FastAPI application."""
    if settings is None:
        settings = PromptManagerSettings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await run_migrations(settings)
        await create_pool(settings)
        yield
        await close_pool()

    app = FastAPI(
        title="Prompt Manager API",
        description=(
            "CRUD API for versioned prompts with A/B experiment routing, "
            "metric collection, and LLM-driven autonomous optimization.\n\n"
            "## Key Features\n"
            "- **Prompts**: Create, version, and manage prompt templates\n"
            "- **Resolve**: Fetch the right prompt version (experiment-aware)\n"
            "- **Experiments**: A/B test prompt versions with weighted routing\n"
            "- **Metrics**: Collect quality signals per prompt version\n"
            "- **Optimize**: Trigger LLM-based prompt improvement via autoresearcher\n\n"
            "## Architecture\n"
            "prompt-manager → autoresearcher-shonku → shonku → agno"
        ),
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Register routers
    app.include_router(prompts.router)
    app.include_router(versions.router)
    app.include_router(experiments.router)
    app.include_router(metrics.router)
    app.include_router(optimize.router)
    app.include_router(resolve.router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
