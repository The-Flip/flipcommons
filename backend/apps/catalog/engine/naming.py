"""Name normalization for catalog duplicate-prevention.

Used across catalog record types (Title, MachineModel, Person, …) whenever
a name needs to be folded to a collision-comparison form. The same rule
applies everywhere: two inputs that normalize to the same string are
considered the same name for duplicate-prevention purposes.

The normalization rule MUST stay in lockstep with the TypeScript copy at
``frontend/src/lib/naming.ts``. Both implementations are covered by a shared
case table; update both and both tests in the same change.

Rule (applied in order):

1. Unicode NFKC, lowercase, casefold.
2. Replace any run of characters that is not an ASCII letter or digit with a
   single space.
3. Strip leading articles: ``the``, ``a``, ``an``.
4. Collapse runs of whitespace and strip edges.

The empty string is a legal output and indicates a name with no
name-bearing characters at all.

Known limitation: NFKC compatibility decomposition expands some decorative
codepoints into letters, so e.g. "Godzilla™" normalizes to "godzillatm"
rather than "godzilla". This is an acceptable trade for the benefit of
folding full-width and composed forms to their ASCII equivalents, which is
the more common case in this project's catalog. Revisit if real titles surface
with decorative marks.
"""

from __future__ import annotations

import re
import unicodedata

_NON_ALNUM_RUN = re.compile(r"[^0-9a-z]+", flags=re.ASCII)
_LEADING_ARTICLE = re.compile(r"^(?:the|a|an)\s+")
_WHITESPACE_RUN = re.compile(r"\s+")

MAX_CATALOG_NAME_LENGTH = 300


def normalize_catalog_name(raw: str) -> str:
    """Return the collision-comparison form of a catalog record name."""
    folded = unicodedata.normalize("NFKC", raw).casefold()
    spaced = _NON_ALNUM_RUN.sub(" ", folded).strip()
    dearticled = _LEADING_ARTICLE.sub("", spaced)
    return _WHITESPACE_RUN.sub(" ", dearticled).strip()
