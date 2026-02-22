"""
Centralised logging configuration for company-agents.

Call setup_logging() once at application startup.
All modules then use logging.getLogger(__name__) as normal and
inherit this configuration through the root logger.

Log level:
  INFO    — default
  DEBUG   — when environment variable DEBUG=true
"""

import logging
import os
import sys


def setup_logging() -> None:
    """Configure the root logger for the application."""
    debug = os.environ.get("DEBUG", "").lower() == "true"
    level = logging.DEBUG if debug else logging.INFO

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(module)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )

    root = logging.getLogger()
    root.setLevel(level)
    # Avoid duplicate handlers if setup_logging() is called more than once
    root.handlers.clear()
    root.addHandler(handler)

    # Silence overly verbose third-party loggers
    logging.getLogger("botframework").setLevel(logging.WARNING)
    logging.getLogger("botbuilder").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    logging.getLogger(__name__).debug("Logging initialised (level=%s).", logging.getLevelName(level))
