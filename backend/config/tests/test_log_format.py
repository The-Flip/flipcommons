"""Railway log severity contract.

Railway derives a plain-text line's severity from its stream, so everything
Python logs to stderr — INFO and WARNING included — arrives tagged
``severity:error`` unless the line is JSON carrying its own ``level``. These
tests pin the JSON shape, the level vocabulary, and the two config sites that
have to keep pointing at the formatter for any of it to reach production.

They also pin what the payload will publish. Railway's log store has no
scrubbing, and ``extra=`` carries whatever Django and its libraries attach to a
record as well as what this codebase passes deliberately.
"""

from __future__ import annotations

import importlib.util
import io
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn

import pytest
from django.conf import settings
from django.http import HttpResponse
from django.test import RequestFactory
from django.utils.log import log_response

from config.log_format import RailwayJSONFormatter, railway_level


def make_record(level: int, msg: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="apps.example",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )


def reject_json_constant(constant: str) -> NoReturn:
    """Python's decoder accepts ``NaN``/``Infinity``; the JSON grammar does not."""
    raise AssertionError(
        f"{constant} is not valid JSON — Railway would reject the line"
    )


def parse_line(rendered: str) -> dict[str, Any]:
    """Parse one rendered line, holding it to what Railway will accept."""
    # A record must occupy exactly one line: Railway ingests line by line, so a
    # raw newline anywhere in the output splits one event into two, the second
    # of which isn't valid JSON and falls back to stream-derived severity.
    assert "\n" not in rendered
    parsed: dict[str, Any] = json.loads(rendered, parse_constant=reject_json_constant)
    return parsed


def format_record(record: logging.LogRecord) -> dict[str, Any]:
    return parse_line(RailwayJSONFormatter().format(record))


@pytest.mark.parametrize(
    ("levelno", "expected"),
    [
        (logging.DEBUG, "debug"),
        (logging.INFO, "info"),
        (logging.WARNING, "warn"),
        (logging.ERROR, "error"),
        (logging.CRITICAL, "error"),
        (logging.INFO + 5, "info"),  # a custom level between the standard ones
        (1, "debug"),
    ],
)
def test_railway_level_vocabulary(levelno: int, expected: str) -> None:
    assert railway_level(levelno) == expected


def test_warning_is_not_reported_as_an_error() -> None:
    """The regression this whole module exists for.

    A WARNING written as plain text to stderr reached the log explorer as
    ``severity:error``, which is what made the error filter useless.
    """
    payload = format_record(make_record(logging.WARNING, "HEIF support unavailable"))

    assert payload["level"] == "warn"
    assert payload["message"] == "HEIF support unavailable"
    assert payload["logger"] == "apps.example"


def test_payload_identifies_the_emitting_process() -> None:
    """Three processes share the stream; a line has to say which one it is."""
    record = make_record(logging.INFO, "booted")

    assert format_record(record)["pid"] == record.process


def test_message_interpolates_args() -> None:
    record = make_record(logging.INFO, "ingested %s patches")
    record.args = (12,)

    assert format_record(record)["message"] == "ingested 12 patches"


def test_traceback_is_folded_into_the_message() -> None:
    """One crash should be one log event, not one event per stack frame."""
    try:
        raise ValueError("boom")
    except ValueError:
        record = make_record(logging.ERROR, "handler failed")
        record.exc_info = sys.exc_info()

    payload = format_record(record)

    assert payload["level"] == "error"
    assert payload["message"].startswith("handler failed\n")
    assert "ValueError: boom" in payload["message"]
    assert "Traceback (most recent call last)" in payload["message"]


def test_non_string_argument_is_stringified() -> None:
    """Interpolation happens before the JSON encoding."""
    record = make_record(logging.INFO, "state: %s")
    record.args = (object(),)

    assert "state: <object object at" in format_record(record)["message"]


def test_extra_fields_become_filterable_attributes() -> None:
    """The reason ``extra=`` is worth emitting at all.

    Railway indexes top-level JSON keys as attributes a query can filter on, so
    a flattened ``user_id`` is reachable where the same value inside the
    message string is not.
    """
    record = make_record(logging.INFO, "authz.deny")
    record.user_id = 42
    record.activity = "catalog.edit"

    payload = format_record(record)

    assert payload["user_id"] == 42
    assert payload["activity"] == "catalog.edit"
    assert payload["message"] == "authz.deny"


def test_record_internals_stay_out_of_the_payload() -> None:
    """Only what the caller passed, never the record's own machinery."""
    payload = format_record(make_record(logging.INFO, "plain"))

    assert set(payload) == {"level", "message", "logger", "time", "pid"}


def test_extra_cannot_overwrite_the_severity() -> None:
    """``level`` is not a LogRecord attribute, so ``logging`` lets it through.

    Without the payload's own fields winning the merge, one such call would
    hand Railway a severity unrelated to the record's real level — the exact
    misclassification this formatter exists to prevent.
    """
    record = make_record(logging.INFO, "surprise")
    record.level = "error"
    record.pid = "nonsense"

    payload = format_record(record)

    assert payload["level"] == "info"
    assert payload["pid"] == record.process


def test_non_scalar_extra_is_dropped() -> None:
    """Only scalars are published, because only scalars were vetted.

    Stringifying whatever an ``extra=`` happens to hold publishes an object's
    repr to a log store with no scrubbing. Railway can only index scalars
    anyway, so nothing filterable is lost.
    """
    record = make_record(logging.INFO, "saving")
    record.entity = object()
    record.entity_id = 7

    payload = format_record(record)

    assert "entity" not in payload
    assert payload["entity_id"] == 7


def test_non_finite_float_extra_is_dropped() -> None:
    """``NaN`` and ``Infinity`` are Python spellings, not JSON ones.

    Emitting one makes the whole line unparseable, so Railway falls back to
    classifying it by its stream — stderr, therefore ``error`` — which is the
    misclassification this formatter exists to prevent.
    """
    record = make_record(logging.INFO, "timing")
    record.duration = float("nan")
    record.overhead = float("inf")
    record.elapsed = 1.5

    rendered = RailwayJSONFormatter().format(record)

    assert "NaN" not in rendered
    assert "Infinity" not in rendered
    payload = parse_line(rendered)
    assert payload["elapsed"] == 1.5
    assert "duration" not in payload
    assert "overhead" not in payload


def test_the_request_django_attaches_to_a_500_stays_out_of_the_payload() -> None:
    """The ``extra=`` caller this codebase does not control.

    ``django.utils.log.log_response`` puts the live ``HttpRequest`` on every
    record it emits, and ``HttpRequest.__repr__`` carries ``get_full_path()``
    — query string included. On the WorkOS callback that string holds a live
    OAuth code, so a formatter willing to stringify the object would publish
    credentials to a log store with no scrubbing on any unhandled 500.

    Driven through the real ``log_response`` rather than a hand-built record so
    that Django renaming or re-shaping the extra fails here.
    """
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RailwayJSONFormatter())
    logger = logging.getLogger("config.tests.django_request")
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR)
    logger.propagate = False
    request = RequestFactory().get("/api/auth/callback/", {"code": "oauth-secret"})
    try:
        log_response(
            "Internal Server Error: %s",
            request.path,
            response=HttpResponse(status=500),
            request=request,
            logger=logger,
        )
    finally:
        logger.removeHandler(handler)

    rendered = stream.getvalue()
    assert "oauth-secret" not in rendered
    payload = parse_line(rendered.rstrip("\n"))
    assert "request" not in payload
    # The scalar Django passes alongside it is still worth filtering on.
    assert payload["status_code"] == 500
    assert payload["level"] == "error"


def test_django_console_handler_uses_the_selected_formatter() -> None:
    """The handler must follow the DEBUG gate rather than naming a formatter."""
    assert (
        settings.LOGGING["handlers"]["console"]["formatter"] == settings.LOG_FORMATTER
    )


def test_production_settings_select_the_json_formatter() -> None:
    """DEBUG=false is the only configuration Railway ever runs.

    Checked in a subprocess because the test runner is a DEBUG=true import of
    the same module, and ``django.test`` overrides ``settings.DEBUG`` on the
    wrapper after the gate has already been evaluated — so nothing in-process
    can observe the branch that actually ships.
    """
    result = subprocess.run(
        [sys.executable, "-c", "import config.settings as s; print(s.LOG_FORMATTER)"],
        # Pinned, not merely inherited: a developer with SENTRY_DSN set would
        # otherwise run a real sentry_sdk.init(environment="production") here
        # and ship a session envelope from a test run, and a
        # MEDIA_STORAGE_BUCKET without its four companion vars would fail the
        # import on a KeyError that has nothing to do with logging.
        env={
            **os.environ,
            "DEBUG": "false",
            "SECRET_KEY": "settings-import-placeholder",  # pragma: allowlist secret
            "SENTRY_DSN": "",
            "MEDIA_STORAGE_BUCKET": "",
        },
        cwd=settings.BASE_DIR,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "json"


def gunicorn_logconfig() -> dict[str, Any]:
    """Load ``logconfig_dict`` out of backend/gunicorn.conf.py.

    Imported by path under a distinct module name because ``gunicorn.conf``
    would shadow the installed gunicorn package.
    """
    path = Path(settings.BASE_DIR) / "gunicorn.conf.py"
    spec = importlib.util.spec_from_file_location("flipcommons_gunicorn_conf", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config: dict[str, Any] = module.logconfig_dict
    return config


def test_gunicorn_and_django_share_one_formatter() -> None:
    """Both Python processes in the container have to agree.

    Gunicorn's master and Django's workers configure logging separately, so a
    formatter wired into only one of them leaves half the container's output
    classified by its stream again.
    """
    gunicorn_formatter = gunicorn_logconfig()["formatters"]["json"]["()"]

    assert gunicorn_formatter is RailwayJSONFormatter
    assert gunicorn_formatter is settings.LOGGING["formatters"]["json"]["()"]


def test_gunicorn_access_log_stays_off() -> None:
    """Caddy owns request logging.

    Supplying ``logconfig_dict`` at all is what enables gunicorn's access log —
    it checks the setting, not just ``--access-logfile`` — so giving this logger
    a handler would silently duplicate every request Caddy already records.
    """
    access = gunicorn_logconfig()["loggers"]["gunicorn.access"]

    assert access["handlers"] == []
    assert access["propagate"] is False
