"""System checks for project-wide contracts.

Run via ``manage.py check`` (model-contract checks also run at server
boot via Django's startup ``system_checks()``). Production-only checks
are gated with ``deploy=True`` and run under ``manage.py check --deploy``
— Railway's ``preDeployCommand`` includes this, so they surface in
deploy logs. Errors block the deploy; Warnings are logged but
non-blocking. See each check function's docstring for its specific
contract.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any, NamedTuple
from urllib.parse import urlparse

from django.apps.config import AppConfig
from django.conf import settings
from django.core.checks import CheckMessage, Error, Tags, Warning, register
from django.core.exceptions import FieldDoesNotExist

from apps.core.models import LinkableModel


@register(Tags.models)
def check_linkable_models(
    app_configs: Sequence[AppConfig] | None,
    # ``**kwargs`` is required by Django's check-framework signature and may
    # carry forward-compatible options (e.g. ``databases``); we don't read
    # any of them, so ``Any`` is the documented type.
    **kwargs: Any,  # noqa: ANN401
) -> list[CheckMessage]:
    """Validate every concrete ``LinkableModel`` subclass.

    Each concrete subclass must:

    - declare non-empty ``entity_type`` and ``entity_type_plural`` strings
      (already validated in ``__init_subclass__``);
    - have unique ``entity_type`` and ``entity_type_plural`` values across
      all subclasses;
    - declare a ``public_id_field`` that resolves to a real concrete model
      field (or the inherited default, ``"slug"``) with ``unique=True``.
    """
    _ = app_configs, kwargs
    errors: list[CheckMessage] = []
    seen_entity_type: dict[str, type] = {}
    seen_entity_type_plural: dict[str, type] = {}

    visited: set[type] = set()

    def walk(cls: type[LinkableModel]) -> None:
        for subclass in cls.__subclasses__():
            if subclass in visited:
                continue
            visited.add(subclass)
            walk(subclass)
            meta = getattr(subclass, "_meta", None)
            if meta is None or meta.abstract:
                continue
            errors.extend(
                _check_one(subclass, seen_entity_type, seen_entity_type_plural)
            )

    # Walk ``LinkableModel`` rather than ``CatalogModel``: this is the
    # structural-contract check, and it must run against every linkable
    # subclass so a future linkable-but-not-catalog model can't bypass the
    # ``entity_type`` / ``public_id_field`` rules. ``apps/core`` also can't
    # depend on ``apps/catalog`` per AppBoundaries. Catalog-local code (the
    # /all/ cache walker, the AI source registry, the wikilink validator)
    # walks ``CatalogModel`` instead — different role, different root.
    #
    # ``LinkableModel`` is abstract; mypy's ``type-abstract`` check flags
    # passing it where a concrete ``type[LinkableModel]`` is expected, but
    # ``__subclasses__()`` is the documented walk entry point.
    walk(LinkableModel)  # type: ignore[type-abstract]
    return errors


def _check_one(
    model: type,
    seen_entity_type: dict[str, type],
    seen_entity_type_plural: dict[str, type],
) -> list[CheckMessage]:
    # ``model`` is typed as ``type`` (not ``type[LinkableModel]``) because the
    # body is fully duck-typed via ``getattr`` and ``model._meta.get_field``.
    # Production callers always pass a ``type[LinkableModel]`` from
    # ``LinkableModel.__subclasses__()``; tests pass synthetic stand-ins to
    # exercise individual error branches without registering real Django
    # models.
    errors: list[CheckMessage] = []

    entity_type = getattr(model, "entity_type", None)
    entity_type_plural = getattr(model, "entity_type_plural", None)

    # ``LinkableModel.__init_subclass__`` validates these at class-creation
    # time, but its abstract-detection ("``entity_type`` in ``cls.__dict__``")
    # is decoupled from Django's ``_meta.abstract``. A concrete-by-Django
    # subclass that simply forgot to declare ``entity_type`` slips past the
    # __init_subclass__ guard and lands here. Backstop it explicitly.
    if not isinstance(entity_type, str) or not entity_type:
        errors.append(
            Error(
                f"{model.__name__} inherits LinkableModel but does not "
                f"declare ``entity_type`` as a non-empty string.",
                obj=model,
                id="core.E106",
            )
        )
    else:
        prior = seen_entity_type.get(entity_type)
        if prior is not None:
            errors.append(
                Error(
                    f"Duplicate LinkableModel.entity_type {entity_type!r}: "
                    f"declared by {prior.__name__} and {model.__name__}.",
                    obj=model,
                    id="core.E101",
                )
            )
        else:
            seen_entity_type[entity_type] = model

    if not isinstance(entity_type_plural, str) or not entity_type_plural:
        errors.append(
            Error(
                f"{model.__name__} inherits LinkableModel but does not "
                f"declare ``entity_type_plural`` as a non-empty string.",
                obj=model,
                id="core.E107",
            )
        )
    else:
        prior = seen_entity_type_plural.get(entity_type_plural)
        if prior is not None:
            errors.append(
                Error(
                    f"Duplicate LinkableModel.entity_type_plural "
                    f"{entity_type_plural!r}: declared by {prior.__name__} "
                    f"and {model.__name__}.",
                    obj=model,
                    id="core.E102",
                )
            )
        else:
            seen_entity_type_plural[entity_type_plural] = model

    public_id_field = getattr(model, "public_id_field", None)
    if not isinstance(public_id_field, str) or not public_id_field:
        errors.append(
            Error(
                f"{model.__name__}.public_id_field must be a non-empty string.",
                obj=model,
                id="core.E103",
            )
        )
        return errors

    # Production callers (``check_linkable_models``) always pass a Django
    # model with ``_meta``; ``getattr`` keeps the duck-typed shape without a
    # narrower static type that would force ignores at the test stand-in
    # call sites.
    meta = getattr(model, "_meta", None)
    if meta is None:
        return errors
    try:
        field = meta.get_field(public_id_field)
    except FieldDoesNotExist:
        errors.append(
            Error(
                f"{model.__name__}.public_id_field={public_id_field!r} "
                f"does not name a field on the model.",
                obj=model,
                id="core.E104",
            )
        )
        return errors

    if not getattr(field, "unique", False):
        errors.append(
            Error(
                f"{model.__name__}.public_id_field={public_id_field!r} "
                f"must reference a field with unique=True.",
                obj=model,
                id="core.E105",
            )
        )

    return errors


@register(Tags.security, deploy=True)
def check_rate_limit_proxy_trust(
    app_configs: Sequence[AppConfig] | None,
    **kwargs: Any,  # noqa: ANN401
) -> list[CheckMessage]:
    """Warn when RATE_LIMIT_TRUST_PROXY_HEADERS is off in a non-DEBUG env.

    The setting gates whether ``apps.core.rate_limits._client_ip`` reads
    proxy-supplied headers. With Caddy on loopback in production, leaving
    it False makes every request key off ``REMOTE_ADDR=127.0.0.1`` — the
    IP-keyed rate limiters silently degrade to one shared bucket. Not a
    security bug (observable, fixable), but easy to overlook because
    nothing crashes. This check raises the missing-env-var case to a
    deploy-time signal so it can't be silently mis-set in Railway.

    See ``docs/Hosting.md`` § "Client IP trust".
    """
    _ = app_configs, kwargs
    if settings.DEBUG or settings.RATE_LIMIT_TRUST_PROXY_HEADERS:
        return []
    return [
        Warning(
            "RATE_LIMIT_TRUST_PROXY_HEADERS is False in a non-DEBUG "
            "environment. IP-keyed rate limiters will silently degrade to "
            "one shared bucket (REMOTE_ADDR=127.0.0.1 behind Caddy on "
            "loopback).",
            hint=(
                "Set RATE_LIMIT_TRUST_PROXY_HEADERS=true in the deployment "
                "environment. See docs/Hosting.md § 'Client IP trust'."
            ),
            id="core.W001",
        )
    ]


def _is_valid_dsn(value: str) -> bool:
    """Shape check for a Sentry DSN: https://<key>@<host>/<project_id>.

    Stricter than a ``startswith("https://")`` prefix check — catches
    ``"https://"``-alone, host-only values, and missing project paths.
    Still a shape assertion, not a probe: we never resolve the host.
    """
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and bool(parsed.netloc)
        and parsed.path.strip("/") != ""
    )


class _SentryEnvVar(NamedTuple):
    """One row of the observability env-var contract.

    ``check_id`` is the operator-facing contract — it lands in deploy
    logs verbatim and is what operators grep for. ``consequence`` is
    appended to the human-readable Error message so the deploy log
    explains what breaks if the var is unset.
    """

    name: str
    check_id: str
    consequence: str
    # Opt-in for the ``https://`` shape check. Set per-row instead of
    # inferred from the var name so a confusingly-named future var can't
    # be silently misclassified.
    is_dsn: bool = False


# Which env vars must be present for Sentry to actually report errors.
_REQUIRED_SENTRY_ENV: tuple[_SentryEnvVar, ...] = (
    _SentryEnvVar(
        name="SENTRY_DSN",
        check_id="core.E201",
        consequence="Backend errors will not be reported to the flipcommons-backend Sentry project.",
        is_dsn=True,
    ),
    _SentryEnvVar(
        name="PUBLIC_SENTRY_DSN",
        check_id="core.E202",
        consequence="SSR and browser errors will not be reported to the flipcommons-frontend Sentry project.",
        is_dsn=True,
    ),
    _SentryEnvVar(
        name="SENTRY_AUTH_TOKEN",
        check_id="core.E203",
        consequence="Frontend sourcemaps will not be uploaded; browser stack traces in Sentry will be minified.",
    ),
    _SentryEnvVar(
        name="SENTRY_ORG",
        check_id="core.E204",
        consequence="Frontend sourcemap upload cannot resolve the Sentry org; uploads will be skipped.",
    ),
    _SentryEnvVar(
        name="SENTRY_PROJECT",
        check_id="core.E205",
        consequence="Frontend sourcemap upload cannot resolve the Sentry project; uploads will be skipped.",
    ),
)


@register(Tags.security, deploy=True)
def check_observability_env(
    app_configs: Sequence[AppConfig] | None,
    **kwargs: Any,  # noqa: ANN401
) -> list[CheckMessage]:
    """Block deploy when required Sentry env vars are missing in production.

    Backend and frontend share a Railway env, so every env var the
    frontend needs (including ``PUBLIC_SENTRY_DSN``, baked into the
    browser bundle at build time) is also readable here.
    """
    _ = app_configs, kwargs
    if settings.DEBUG:
        return []
    messages: list[CheckMessage] = []
    for spec in _REQUIRED_SENTRY_ENV:
        value = os.environ.get(spec.name, "").strip()
        if not value:
            messages.append(
                Error(
                    f"{spec.name} is empty in a non-DEBUG environment. {spec.consequence}",
                    hint=f"Set {spec.name} on the Railway service.",
                    id=spec.check_id,
                )
            )
            continue
        if spec.is_dsn and not _is_valid_dsn(value):
            messages.append(
                Error(
                    f"{spec.name} is set but is not a valid Sentry DSN "
                    "(expected https://<key>@<host>/<project_id>).",
                    hint=f"Confirm {spec.name} on Railway matches the DSN shown in Sentry → Settings → Client Keys (DSN).",
                    id=spec.check_id,
                )
            )
    # Architectural invariant: backend errors go to flipcommons-backend,
    # frontend (SSR + browser) errors go to flipcommons-frontend. The two
    # DSNs must point at different projects. Equal values silently route
    # one half's errors into the other project — the exact silent
    # degradation this check exists to prevent.
    backend_dsn = os.environ.get("SENTRY_DSN", "").strip()
    frontend_dsn = os.environ.get("PUBLIC_SENTRY_DSN", "").strip()
    if backend_dsn and frontend_dsn and backend_dsn == frontend_dsn:
        messages.append(
            Error(
                "SENTRY_DSN and PUBLIC_SENTRY_DSN are set to the same value. "
                "They must point at different Sentry projects "
                "(flipcommons-backend vs flipcommons-frontend); equal values "
                "route one half's errors into the wrong project.",
                hint="Confirm each DSN on Railway against Sentry → Settings → Client Keys for its respective project.",
                id="core.E206",
            )
        )
    if not os.environ.get("RAILWAY_GIT_COMMIT_SHA", "").strip():
        # Sourcemaps are uploaded against this SHA as the release tag.
        # If runtime events don't carry the same release, Sentry can't
        # match them to the uploaded sourcemaps and stack traces show
        # as minified — the same failure mode as a missing
        # SENTRY_AUTH_TOKEN. Railway normally injects this; if it's
        # missing, refuse to promote rather than silently degrade.
        messages.append(
            Error(
                "RAILWAY_GIT_COMMIT_SHA is empty in a non-DEBUG environment. "
                "Sentry events will have no release tag, so uploaded "
                "sourcemaps will not resolve and browser stack traces will "
                "show as minified.",
                hint="Railway normally injects this automatically — investigate why it is missing.",
                id="core.E207",
            )
        )
    return messages


# The literal env-var values that `isDeploymentSearchEngineIndexable()`
# accepts. The SvelteKit helper only treats `"true"` as on, but the
# deploy-time check additionally requires `"false"` as the explicit
# opt-out — anything else (including unset, `"1"`, `"yes"`, `"True"`)
# fails so operators must declare intent on every deployed service.
_ALLOWED_INDEXING_VALUES: frozenset[str] = frozenset({"true", "false"})


@register(Tags.security, deploy=True)
def check_search_engine_indexing_env(
    app_configs: Sequence[AppConfig] | None,
    **kwargs: Any,  # noqa: ANN401
) -> list[CheckMessage]:
    """Block deploy when ALLOW_SEARCH_ENGINE_INDEXING is missing or malformed.

    The SvelteKit `robots.txt` and (later) `sitemap.xml` endpoints read
    this env var via `isDeploymentSearchEngineIndexable()` to decide
    whether to expose crawlable signals. Read-time default is off, so
    an unset preview won't *leak*; this deploy check exists to force
    every deployed service (prod, staging, every preview) to *declare*
    intent — otherwise prod can ship with the var unset, default off,
    and silently drop out of search indexes for weeks before anyone
    notices traffic crater.

    Backend and frontend share the Railway env (per `docs/DeployChecks.md`
    § "Frontend checks belong in Python"), so this check runs server-side
    and reads `os.environ` directly. It never probes the running service.

    Unlike the sibling `check_observability_env` / `check_rate_limit_proxy_trust`,
    this check intentionally does NOT short-circuit on ``settings.DEBUG``:
    reproducing the deploy gate locally per `docs/DeployChecks.md`
    § "Running deploy checks locally" is part of the contract, and the
    cost of setting a single bool to verify is nil.
    """
    _ = app_configs, kwargs
    # Read the raw value without stripping: the SvelteKit helper does a
    # strict `=== 'true'` comparison, so a Railway-input value like
    # " true " (trailing space) would silently misclassify — pass the
    # backend check, then read as off at runtime, then prod drops out of
    # search indexes. Rejecting any whitespace at the check keeps the two
    # halves of the contract in lockstep.
    raw = os.environ.get("ALLOW_SEARCH_ENGINE_INDEXING", "")
    if not raw:
        return [
            Error(
                "ALLOW_SEARCH_ENGINE_INDEXING is empty. Every deployed "
                "service must declare crawler-indexing intent explicitly.",
                hint=(
                    'Set ALLOW_SEARCH_ENGINE_INDEXING="true" on the '
                    'production Railway service and "false" on every '
                    "other deployed service (preview, staging)."
                ),
                id="core.E301",
            )
        ]
    if raw not in _ALLOWED_INDEXING_VALUES:
        return [
            Error(
                f"ALLOW_SEARCH_ENGINE_INDEXING={raw!r} is not a recognised "
                'value. Only the literal "true" or "false" is accepted.',
                hint=(
                    'Set ALLOW_SEARCH_ENGINE_INDEXING to "true" (production) '
                    'or "false" (every other deployed service). Values like '
                    '"1", "yes", or "True" are rejected so a typo cannot '
                    "silently disable production indexing."
                ),
                id="core.E302",
            )
        ]
    return []


def _is_valid_site_origin(value: str) -> bool:
    """Shape check for SITE_ORIGIN: ``https://<host>`` with no path.

    Kept in lockstep with the build-phase regex in
    ``frontend/svelte.config.js`` (``^https://[^/?#]+$``) so a value that
    passes the build can't be rejected at deploy time, or vice versa.
    Rejects ``http://``, trailing slashes, paths, query strings, and
    fragments — production canonical URLs and the sitemap's ``Sitemap:``
    line are built by string concatenation, so a stray suffix silently
    produces double-slashes or garbage URLs downstream.
    """
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and bool(parsed.netloc)
        and parsed.path == ""
        and parsed.query == ""
        and parsed.fragment == ""
    )


@register(Tags.security, deploy=True)
def check_site_origin(
    app_configs: Sequence[AppConfig] | None,
    **kwargs: Any,  # noqa: ANN401
) -> list[CheckMessage]:
    """Block deploy when SITE_ORIGIN is missing or malformed.

    SITE_ORIGIN is consumed by the SvelteKit build for prerendered meta
    tags (canonical URLs, OG tags) and by the runtime ``/sitemap.xml``
    and ``/robots.txt`` endpoints. Today ``frontend/svelte.config.js``
    falls back to ``http://localhost:5173`` when unset — fine for ``make
    dev``, but a production build with the var unset silently bakes
    localhost URLs into prerendered HTML.

    The build-phase gate in ``svelte.config.js`` already refuses Railway
    builds without SITE_ORIGIN. This deploy check is defense in depth:
    it catches the case where SITE_ORIGIN drifted between build and
    deploy (or was never set on a freshly created service), and it
    surfaces the failure with an operator-grep-friendly id.

    Unlike ``check_search_engine_indexing_env``, this check short-
    circuits on ``settings.DEBUG``: ``svelte.config.js`` falls back to
    ``http://localhost:5173`` when the var is unset, so requiring an
    explicit value locally would just add friction without catching any
    deployment risk.
    """
    _ = app_configs, kwargs
    if settings.DEBUG:
        return []
    raw = os.environ.get("SITE_ORIGIN", "").strip()
    if not raw:
        return [
            Error(
                "SITE_ORIGIN is empty in a non-DEBUG environment. "
                "Canonical URLs, OG tags, robots.txt, and the sitemap "
                "will point at incorrect or relative hosts.",
                hint=(
                    "Set SITE_ORIGIN=https://<host> on the Railway service "
                    "(production is https://flipcommons.org)."
                ),
                id="core.E303",
            )
        ]
    if not _is_valid_site_origin(raw):
        return [
            Error(
                f"SITE_ORIGIN={raw!r} is not a valid origin "
                "(expected https://<host> with no path, trailing slash, "
                "query string, or fragment).",
                hint=(
                    "Set SITE_ORIGIN=https://<host> on the Railway service "
                    "(production is https://flipcommons.org). The value is "
                    "concatenated with paths to build canonical URLs, so a "
                    "trailing slash or stray path produces broken links."
                ),
                id="core.E304",
            )
        ]
    return []
