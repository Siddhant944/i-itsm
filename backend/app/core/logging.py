"""Logging setup: one plain, timestamped format for the whole app (UTC).

Only the handler this module installed is replaced on a second call, so configuring the app
twice in one process — which the tests do — never silences a handler someone else attached.
"""

import logging
import time

HANDLER_NAME = "itsm"


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger. Safe to call repeatedly, and safe for test capture."""
    formatter = logging.Formatter("%(asctime)sZ %(levelname)-7s %(name)s: %(message)s")
    formatter.converter = time.gmtime
    handler = logging.StreamHandler()
    handler.set_name(HANDLER_NAME)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    for existing in [h for h in root.handlers if h.get_name() == HANDLER_NAME]:
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())
