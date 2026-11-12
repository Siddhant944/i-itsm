"""Logging setup: one plain, timestamped format for the whole app (UTC).

Only the handler this module installed is replaced on a second call, so configuring the app
twice in one process — which the tests do — never silences a handler someone else attached.
"""

import logging
import time

HANDLER_NAME = "itsm"
#: HTTP client loggers print every request URL at INFO, and the Telegram Bot API puts the bot
#: token in the URL (P4 review). Only their warnings are ever wanted.
QUIET_LOGGERS = ("httpx", "httpcore")


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
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
