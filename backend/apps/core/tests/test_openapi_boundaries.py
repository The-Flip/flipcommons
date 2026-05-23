"""Cross-cutting boundary tests for the OpenAPI surface.

These pin the live OpenAPI naming and schema-boundary conventions. Targets are
the generated OpenAPI doc and module introspection, not text-pattern checks
against source files.
"""

from __future__ import annotations

import importlib
import inspect
import re

import pytest
from ninja import Schema

from apps.core.authz.route_walker import iter_operations
from apps.provenance.rate_limits import get_rate_limit_spec
from config.api import api

ALLOWED_SUFFIXES = ("Schema", "Ref")
FORBIDDEN_GENERIC_NAMES = frozenset(
    {
        "Variant",
        "Source",
        "Stats",
        "Recognition",
        "Create",
        "Input",
        "SearchResponse",
        "Ref",
    }
)
# `Activity` is the authz `StrEnum` referenced by `AuthStatusSchema.capabilities`;
# pydantic emits the enum as a top-level component because the same enum is
# used as a `dict[Activity, bool]` key. Bare-name allowlist rather than a
# rename — `ActivitySchema` would lie about what the type is.
ALLOWED_BARE_NAMES = frozenset({"JsonBody", "Activity"})

MUTATING_METHODS = frozenset({"post", "patch", "delete"})

# Mutating endpoints that legitimately have no 4xx response. Adding to this
# allowlist requires justification.
NO_4XX_ALLOWLIST = frozenset(
    {
        # Logout takes no body, can't fail validation, returns
        # AuthStatusSchema unconditionally.
        ("/api/auth/logout/", "post"),
    }
)

# Per-app baselines for inline-schema regression check. Schemas should live
# in `schemas.py`, but pre-existing inline definitions are grandfathered.
# The test fails if any app's count grows beyond its baseline; lowering a
# baseline (i.e. migrating inline schemas into schemas.py) is welcome.
INLINE_SCHEMA_BASELINES = {
    "apps.accounts.api": 0,
    "apps.accounts.api.auth": 0,
    "apps.accounts.api.profile": 0,
    "apps.accounts.api.signup": 0,
    "apps.citation.api": 0,
    "apps.media.api": 0,
    "apps.provenance.api": 0,
}


class TestSchemaSuffixDiscipline:
    """Every name in components.schemas conforms to the rationalized rules."""

    @pytest.fixture(scope="class")
    def schema_names(self) -> list[str]:
        return list(api.get_openapi_schema()["components"]["schemas"].keys())

    def test_all_names_use_allowed_suffix_or_bare(self, schema_names: list[str]):
        violations = [
            name
            for name in schema_names
            if name not in ALLOWED_BARE_NAMES and not name.endswith(ALLOWED_SUFFIXES)
        ]
        assert not violations, (
            "Every component schema name must end in 'Schema' or 'Ref', or "
            f"be one of {sorted(ALLOWED_BARE_NAMES)}. Violations: {violations}"
        )

    def test_no_in_or_out_suffix(self, schema_names: list[str]):
        violations = [name for name in schema_names if name.endswith(("In", "Out"))]
        assert not violations, (
            "Schema names must not end in 'In' or 'Out' (use 'Input' or a "
            f"role suffix instead). Violations: {violations}"
        )

    def test_no_forbidden_generic_names(self, schema_names: list[str]):
        violations = sorted(set(schema_names) & FORBIDDEN_GENERIC_NAMES)
        assert not violations, (
            "These generic names were eliminated by the rename and must not "
            f"reappear in components.schemas: {violations}"
        )


class TestInlineSchemaRegression:
    """Schemas should live in schemas.py, not inline in endpoint files.

    Pre-existing inline definitions are grandfathered via per-app baselines.
    The test fails if any app's inline count grows; new schemas must go in
    schemas.py.
    """

    @pytest.mark.parametrize(
        ("module_path", "baseline"), sorted(INLINE_SCHEMA_BASELINES.items())
    )
    def test_inline_schema_count_does_not_grow(self, module_path: str, baseline: int):
        module = importlib.import_module(module_path)
        inline = [
            name
            for name, obj in inspect.getmembers(module, inspect.isclass)
            if obj.__module__ == module_path and issubclass(obj, Schema)
        ]
        assert len(inline) <= baseline, (
            f"{module_path} has {len(inline)} inline Schema classes "
            f"(baseline: {baseline}). New schemas must be defined in "
            f"the app's schemas.py instead. Inline classes found: "
            f"{sorted(inline)}"
        )


class TestMutatingEndpointsHave4xx:
    """Every mutating endpoint declares at least one 4xx response.

    `ValidationErrorSchema` and `RateLimitErrorSchema` give the frontend
    typed access to error bodies; this test ensures mutating endpoints
    actually wire them in (or some other 4xx).
    """

    def test_post_patch_delete_declare_4xx_responses(self):
        paths = api.get_openapi_schema()["paths"]
        violations: list[tuple[str, str]] = []
        for path, methods in paths.items():
            for method, operation in methods.items():
                if method not in MUTATING_METHODS:
                    continue
                if (path, method) in NO_4XX_ALLOWLIST:
                    continue
                response_codes = operation.get("responses", {}).keys()
                if not any(400 <= int(code) < 500 for code in response_codes):
                    violations.append((path, method))
        assert not violations, (
            "These mutating endpoints declare no 4xx response. Add typed "
            "error responses (ValidationErrorSchema, RateLimitErrorSchema, "
            "etc.) or add to NO_4XX_ALLOWLIST with justification: "
            f"{violations}"
        )


class TestRateLimitedEndpointsDeclare429:
    """Every ``@rate_limited`` route must advertise ``429: RateLimitErrorSchema``.

    The decorator can raise ``RateLimitExceededError`` → 429 at request
    time, but the OpenAPI response map is hand-written on
    ``@router.<verb>(... response={...})`` and the decorator can't
    fabricate it. This boundary test makes the omission visible.
    """

    # `iter_operations` yields paths with Ninja's typed-converter syntax
    # (`{path:public_id}`); OpenAPI strips the converter prefix
    # (`{public_id}`). Match the OpenAPI form.
    _STRIP_CONVERTER = re.compile(r"\{[^:}]+:([^}]+)\}")

    def test_rate_limited_routes_declare_429(self):
        paths = api.get_openapi_schema()["paths"]
        missing: list[str] = []
        for method, path, view in iter_operations(api):
            if get_rate_limit_spec(view) is None:
                continue
            full_path = f"/api{self._STRIP_CONVERTER.sub(r'{\1}', path)}"
            method_lc = method.lower()
            responses = paths.get(full_path, {}).get(method_lc, {}).get("responses", {})
            # Ninja keys the responses dict by int when registered via
            # `response={429: ...}`; the rendered JSON OpenAPI doc keys
            # by string. ``get_openapi_schema()`` returns the live dict
            # (int keys today) — accept either so a future Ninja
            # normalization doesn't silently report "missing 429"
            # everywhere.
            entry = responses.get(429) or responses.get("429") or {}
            schema_ref = (
                entry.get("content", {}).get("application/json", {}).get("schema", {})
            )
            ref = schema_ref.get("$ref", "")
            if not ref.endswith("/RateLimitErrorSchema"):
                missing.append(
                    f"{method} {full_path} → {view.__module__}.{view.__qualname__}"
                )
        assert not missing, (
            "These @rate_limited routes don't declare "
            "`429: RateLimitErrorSchema` in their response map:\n  "
            + "\n  ".join(missing)
        )
