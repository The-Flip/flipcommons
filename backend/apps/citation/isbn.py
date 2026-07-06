"""Pure ISBN helpers: normalization and checksum validation.

A dependency-free leaf (like ``hosts``), so both the input-classification
tier (``extraction.classify_input``) and the deliverer interpretation tier
(``deliverers.embedded_isbn``) can share one grammar without a layering
knot — the two consumers sit on opposite sides of ``models`` in the app's
import stack.

``normalize_isbn`` is shape-only (the historical contract of the ISBN paste
path — Open Library is the arbiter of existence). ``isbn_checksum_ok`` is
the stricter gate for ISBN candidates *mined out of* URLs and page metadata,
where a coincidental digit run must not trigger a bogus lookup.
"""

from __future__ import annotations


def normalize_isbn(raw: str) -> str | None:
    """Strip hyphens/spaces and return a 10- or 13-digit ISBN shape, or None.

    Shape-only — no checksum. Kept lenient deliberately: a contributor's
    hand-typed ISBN with a typo should reach Open Library and fail with a
    clear "not found" rather than being silently reclassified as free text.
    """
    stripped = raw.replace("-", "").replace(" ", "").upper()
    if len(stripped) == 13 and stripped.isdigit():
        return stripped
    if len(stripped) == 10 and stripped[:9].isdigit() and stripped[9] in "0123456789X":
        return stripped
    return None


def isbn_checksum_ok(isbn: str) -> bool:
    """Whether a normalized 10/13-digit ISBN has a valid check digit.

    Expects :func:`normalize_isbn` output (verified shape, uppercase ``X``);
    any other length returns False rather than raising, so callers can gate
    un-normalized candidates in one expression.
    """
    if len(isbn) == 10:
        total = 0
        for position, char in enumerate(isbn):
            value = 10 if char == "X" else int(char)
            total += (10 - position) * value
        return total % 11 == 0
    if len(isbn) == 13:
        total = sum(int(char) * (1 if i % 2 == 0 else 3) for i, char in enumerate(isbn))
        return total % 10 == 0
    return False
