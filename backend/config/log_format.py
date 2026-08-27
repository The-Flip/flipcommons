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
import math
from datetime import UTC, datetime
from typing import Any, TypeIs

# Derived from a live record rather than hand-listed so the set tracks the
# interpreter — `taskName` arrived in 3.12, and a literal set would leak
# whatever the next version adds into every payload. `message` and `asctime`
# are absent from a fresh record but get set by `logging.Formatter`.
_RESERVED_RECORD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime"}

# bool is an int subclass, so it needs no entry of its own.
_EMITTABLE_SCALARS = (str, int, type(None))

type LogAttribute = str | int | float | None
"""A value this formatter is willing to publish as a Railway log attribute."""


def _is_emittable(value: object) -> TypeIs[LogAttribute]:
    """Whether an ``extra=`` value may be published.

    ``extra=`` is not a channel this codebase controls end to end.
    ``django.utils.log.log_response`` attaches the live ``HttpRequest`` to
    every record it emits, and that object's repr carries the full query
    string, the WorkOS callback's ``?code=`` included. Railway's log store
    has no scrubbing, so stringifying arbitrary objects would publish a live
    OAuth code on any unhandled 500. Scalars are also the only thing Railway
    can usefully index, so nothing filterable is lost by refusing the rest.

    ``TypeIs`` rather than ``bool`` names in the signature which type this
    answers for. It buys no checking: the body is not verified against the
    narrowed type, and the one call site passes ``Any`` because
    ``LogRecord.__dict__`` is ``dict[str, Any]``. Widening ``LogAttribute``
    still means widening the check by hand.
    """
    if isinstance(value, _EMITTABLE_SCALARS):
        return True
    # NaN and the infinities serialize to bare `NaN`/`Infinity`, which no JSON
    # parser accepts. Railway would fall back to classifying the line by the
    # stream it arrived on — the misclassification this formatter exists to
    # prevent, reintroduced through the extras channel.
    return isinstance(value, float) and math.isfinite(value)


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
        # Extras first so the fields below win a name collision. `logging`
        # rejects an `extra` key that shadows a record attribute, but `level`,
        # `logger`, `time` and `pid` are ours rather than the record's, so
        # `extra={"level": "debug"}` reaches us and would otherwise overwrite
        # the severity Railway reads.
        payload: dict[str, LogAttribute] = {
            **self._extras(record),
            "level": railway_level(record.levelno),
            "message": self._message(record),
            "logger": record.name,
            "time": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            # Gunicorn's master and both workers interleave in one stream, and
            # only gunicorn's own lines name their pid in the text. Without
            # this, two workers logging the same warning are indistinguishable.
            "pid": record.process,
        }
        # No `default=` fallback: every value here is a JSON scalar by
        # construction, so the encoder has nothing to fall back on. A fallback
        # would only mask an extra that `_is_emittable` should have refused.
        return json.dumps(payload)

    def _extras(self, record: logging.LogRecord) -> dict[str, LogAttribute]:
        """The scalars the caller passed as ``extra=``.

        Flattened into the payload rather than nested, because Railway indexes
        top-level JSON keys as attributes you can filter a query on — which is
        the only reason these fields are worth emitting. Anything that survives
        ``_is_emittable`` is therefore stored by Railway unscrubbed, so keep
        personal data out of ``extra=``; see docs/Observability.md.
        """
        return {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED_RECORD_ATTRS and _is_emittable(value)
        }

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
