"""Logging setup: one plain, timestamped format for the whole app (UTC)."""

import logging
import time


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger once; safe to call repeatedly."""
    formatter = logging.Formatter("%(asctime)sZ %(levelname)-7s %(name)s: %(message)s")
    formatter.converter = time.gmtime
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
