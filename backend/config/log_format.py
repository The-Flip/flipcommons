"""JSON log formatting for Railway's log explorer.

Railway assigns each log line a ``severity`` it can filter on. For a plain-text
line that severity comes from the stream it arrived on — stdout becomes
``info``, stderr becomes ``error`` — and Python's ``StreamHandler`` writes to
stderr, so unformatted INFO and WARNING lines arrive tagged as errors and
``severity:error`` matches nothing but noise. A line that is valid JSON is read
instead of its stream, and its ``level`` field becomes the severity, which is
what this formatter emits.

The handler's stream is left at the ``StreamHandler`` default, stderr. Once a
line is JSON its ``level`` decides the severity, so the stream that carried it
stops mattering and moving these logs to stdout would not reclassify them.

See https://docs.railway.com/guides/logs for the normalization rules.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any


def railway_level(levelno: int) -> str:
    """Map a Python level number onto Railway's four-value vocabulary.

    Thresholds rather than a name lookup so custom levels registered between
    the standard ones classify sensibly instead of falling off the end.
    CRITICAL collapses into ``error`` because Railway has nothing above it.
    """
    if levelno >= logging.ERROR:
        return "error"
    if levelno >= logging.WARNING:
        return "warn"
    if levelno >= logging.INFO:
        return "info"
    return "debug"


class RailwayJSONFormatter(logging.Formatter):
    """Render a record as one JSON line Railway can classify and filter."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, str | int | None] = {
            "level": railway_level(record.levelno),
            "message": self._message(record),
            "logger": record.name,
            "time": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            # Gunicorn's master and both workers interleave in one stream, and
            # only gunicorn's own lines name their pid in the text. Without
            # this, two workers logging the same warning are indistinguishable.
            "pid": record.process,
        }
        return json.dumps(payload)

    def _message(self, record: logging.LogRecord) -> str:
        """The formatted message with any traceback folded into it.

        Keeping the traceback inside the JSON string makes a failure one log
        event. Written raw to the stream it is one stderr line per frame, each
        classified on its own, so a single crash fills the explorer with dozens
        of unrelated-looking entries.
        """
        parts = [record.getMessage()]
        if record.exc_info:
            parts.append(self.formatException(record.exc_info))
        if record.stack_info:
            parts.append(self.formatStack(record.stack_info))
        return "\n".join(parts)


JSON_FORMATTER_SPEC: dict[str, Any] = {"()": RailwayJSONFormatter}
"""The ``dictConfig`` formatter entry, shared by the container's two Python processes.

Django configures logging through ``settings.LOGGING`` and gunicorn through
``logconfig_dict`` in gunicorn.conf.py. They have to agree, or half the
container's output goes back to being classified by its stream.

Naming the class rather than a dotted path means a rename fails at import
instead of at container boot, where gunicorn re-raises an unresolvable path as
a RuntimeError and takes the deploy down.
"""
