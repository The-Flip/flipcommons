"""Catalog domain exceptions.

Structured errors raised by catalog domain helpers (claim editing, location
validation, …). They subclass ``StructuredApiError`` so the single handler in
``config/api.py`` renders them as ``{detail: {kind, message, ...}}`` bodies,
following the same convention as ``accounts.auth_errors`` and
``core.rate_limits`` — errors live in a domain module, not under ``api/``.
"""

from __future__ import annotations

from apps.core.exceptions import StructuredApiError
from apps.core.types import JsonBody


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
