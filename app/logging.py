from __future__ import annotations

import logging
from logging.config import dictConfig


def configure_logging(level: str = "INFO") -> None:
    """Configure application logging once at startup."""

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "level": level,
                }
            },
            "loggers": {
                "httpx": {
                    "handlers": ["console"],
                    "level": "WARNING",
                    "propagate": False,
                },
                "httpcore": {
                    "handlers": ["console"],
                    "level": "WARNING",
                    "propagate": False,
                },
            },
            "root": {"handlers": ["console"], "level": level},
        }
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
