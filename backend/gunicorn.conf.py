"""Gunicorn runtime config. Loaded via --config in scripts/start-production.

Only logging lives here. Gunicorn's error logger carries its INFO boot and
shutdown lines on the same channel as real errors, so no choice of stream
classifies both: Railway reads plain text on stderr (the default) as
``severity:error`` and would read it on stdout as ``info``. Giving that logger
the JSON formatter Django uses classifies each line by its real level. See
config/log_format.py.
"""

from __future__ import annotations

from config.log_format import JSON_FORMATTER_SPEC

logconfig_dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": JSON_FORMATTER_SPEC},
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
    },
    # propagate=False throughout: gunicorn's own defaults leave these loggers
    # propagating into a root that also has a console handler, which would
    # print every line twice once we give root one.
    "loggers": {
        "gunicorn.error": {
            "level": "INFO",
            "handlers": ["console"],
            "propagate": False,
        },
        # Deliberately handler-less. Setting logconfig_dict at all turns
        # gunicorn's access log on (Logger.access() checks the setting, not
        # just --access-logfile), and Caddy already logs every request with
        # more detail — duration, upstream, real client IP. Letting both log
        # would double request volume in the explorer to say less.
        "gunicorn.access": {
            "level": "INFO",
            "handlers": [],
            "propagate": False,
        },
    },
    "root": {"level": "INFO", "handlers": ["console"]},
}
