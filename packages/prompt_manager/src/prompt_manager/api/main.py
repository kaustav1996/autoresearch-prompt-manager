"""Entrypoint: run the API server with uvicorn."""

from __future__ import annotations

import logging
import sys

import uvicorn

from prompt_manager.api.app import create_app
from prompt_manager.core.config import PromptManagerSettings


def _configure_logging(level: str = "info") -> None:
    """Set up structured logging for the application."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )
    # Quiet noisy libraries
    logging.getLogger("asyncpg").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def main() -> None:
    settings = PromptManagerSettings()
    _configure_logging(settings.log_level if hasattr(settings, "log_level") else "info")

    logger = logging.getLogger("prompt_manager")
    logger.info("Starting Prompt Manager API on %s:%s", settings.host, settings.port)

    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
