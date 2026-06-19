"""Shared structured API errors.

``StructuredApiError`` is the base; subclasses declare ``kind`` and ``status``
as class-level constants and implement ``to_body()`` to return the
variant-specific body fields. The single handler in ``config/api.py`` wraps the
response uniformly:

    {"detail": {"kind": <kind>, "message": <message>, **to_body()}}

Use ``extra_headers()`` to attach response headers (e.g. ``Retry-After``).

Subclass dispatch is automatic: django-ninja's ``@api.exception_handler``
matches by ``isinstance`` (walks the MRO), so registering one handler
against ``StructuredApiError`` routes every subclass through it.

``StructuredValidationError`` is the one domain-agnostic concrete subclass that
lives here beside the base: a field/form validation 422 raised across the
catalog write paths. Domain-specific structured errors live in their own app's
module (e.g. ``accounts.auth_errors``, ``core.rate_limits``).
"""

from __future__ import annotations

from typing import ClassVar

from apps.core.types import JsonBody


class StructuredApiError(Exception):
    """Base for exceptions that produce structured ``{detail: {kind, ...}}`` bodies."""

    kind: ClassVar[str]
    status: ClassVar[int]

    def __init_subclass__(cls, **kw: object) -> None:
        super().__init_subclass__(**kw)
        for attr in ("kind", "status"):
            if attr not in cls.__dict__:
                raise TypeError(f"{cls.__name__} must define class attribute {attr!r}")

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def to_body(self) -> JsonBody:
        """Return variant-specific body fields. ``kind`` and ``message``
        are added by the handler; do not include them here."""
        return {}

    def extra_headers(self) -> dict[str, str]:
        """Optional response headers. Override for e.g. ``Retry-After``."""
        return {}


class StructuredValidationError(StructuredApiError):
    """Validation error with separate field-level and form-level messages.

    Raised by claim-editing helpers and routed through the shared
    ``StructuredApiError`` handler in ``config/api.py``, which returns a
    422 JSON response:

    .. code-block:: json

        {
            "detail": {
                "kind": "validation_error",
                "message": "summary",
                "field_errors": {"year": "Must be ≤ 2100."},
                "form_errors": ["No changes provided."]
            }
        }
    """

    kind = "validation_error"
    status = 422

    def __init__(
        self,
        *,
        message: str,
        field_errors: dict[str, str] | None = None,
        form_errors: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.field_errors = field_errors or {}
        self.form_errors = form_errors or []

    def to_body(self) -> JsonBody:
        return {
            "field_errors": self.field_errors,
            "form_errors": self.form_errors,
        }
