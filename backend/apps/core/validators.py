"""Shared validators for catalog data."""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError

# System-wide slug shape: lowercase ASCII letters/digits, single hyphens
# between segments, no leading/trailing/repeated hyphens. Stricter than
# Django's stock ``validate_slug``, which allows uppercase, underscores,
# and any hyphen placement. Owned here so the create and edit paths stay
# in sync (see ``apps.catalog.api.entity_create.validate_slug_format``
# and ``apps.provenance.validation.validate_claim_value``).
# ``\A``/``\Z``, not ``^``/``$``: consumers call this via ``match`` and
# ``search`` (Django's ``RegexValidator``) as well as ``fullmatch``, and a
# ``$`` anchor lets those first two accept one trailing newline — a slug
# that saves but that exact-equality resolution can never reach.
SLUG_RE = re.compile(r"\A[a-z0-9]+(?:-[a-z0-9]+)*\Z")
SLUG_FORMAT_MESSAGE = (
    "Slug may contain only lowercase letters, digits, and hyphens, "
    "with no leading, trailing, or repeated hyphens."
)


def validate_no_mojibake(value: object) -> None:
    """Reject text containing mojibake (encoding-corruption artifacts).

    Detects UTF-8 text that was misinterpreted as Latin-1 or Windows-1252
    by attempting to reverse the corruption. If re-encoding as cp1252 and
    decoding as UTF-8 produces different (valid) text, the original was
    garbled. Also rejects the Unicode replacement character (U+FFFD).

    Legitimate accented characters (é, ü, ñ) pass through fine.
    """
    if not isinstance(value, str) or not value:
        return

    if "\ufffd" in value:
        raise ValidationError(
            "Text contains a replacement character (�), indicating encoding corruption."
        )

    for encoding in ("cp1252", "latin-1"):
        try:
            recovered = value.encode(encoding).decode("utf-8")
        except UnicodeDecodeError, UnicodeEncodeError:
            continue
        if recovered != value:
            raise ValidationError(
                "Text contains mojibake (garbled encoding). "
                "Check for copy-paste artifacts or encoding issues."
            )
