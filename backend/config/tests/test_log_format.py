"""Railway log severity contract.

Railway derives a plain-text line's severity from its stream, so everything
Python logs to stderr — INFO and WARNING included — arrives tagged
``severity:error`` unless the line is JSON carrying its own ``level``. These
tests pin the JSON shape, the level vocabulary, and the two config sites that
have to keep pointing at the formatter for any of it to reach production.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings

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


def format_record(record: logging.LogRecord) -> dict[str, Any]:
    rendered = RailwayJSONFormatter().format(record)
    # A record must occupy exactly one line: Railway ingests line by line, so a
    # raw newline anywhere in the output splits one event into two, the second
    # of which isn't valid JSON and falls back to stream-derived severity.
    assert "\n" not in rendered
    parsed: dict[str, Any] = json.loads(rendered)
    return parsed


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
    """Why the payload needs no ``default=`` on ``json.dumps``.

    Interpolation happens before the JSON encoding, so an argument of any type
    reaches the encoder already flattened into the message string and no
    logging call can hand it something un-serializable.
    """
    record = make_record(logging.INFO, "state: %s")
    record.args = (object(),)

    assert "state: <object object at" in format_record(record)["message"]


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
