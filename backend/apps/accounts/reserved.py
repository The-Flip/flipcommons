"""Reserved-username policy.

Source-of-truth lists for stems and affixes that convey authority. Matching
is equality (not substring) on a normalized form, so `flipperjones` is not
blocked by stem `flip`, but `flip2024` is — digits strip out and the residue
equals the stem.
"""

from __future__ import annotations

from apps.accounts.types import Username

# normalize() strips hyphens and other non-letters, so hyphenated variants
# like "flip-commons" and "the-museum" fold automatically — only the folded
# forms need to be listed here.
STEMS: frozenset[str] = frozenset(
    {
        "flipcommons",
        "flip",
        "theflip",
        "museum",
        "themuseum",
    }
)

AFFIXES: frozenset[str] = frozenset(
    {
        "official",
        "team",
        "staff",
        "admin",
        "administrator",
        "help",
        "system",
        "mod",
        "moderator",
        "sysadmin",
        "superuser",
        "support",
    }
)

# Common homoglyph substitutions used INTERIOR to a candidate. Applied
# only after leading/trailing digit runs are stripped, so an edge `0` is
# treated as padding (`admin0` → `admin`) rather than a letter substitute
# (`admin0` is not a credible spelling of `admino`).
_HOMOGLYPHS = str.maketrans({"0": "o", "1": "l"})


def normalize(s: str) -> str:
    """Lowercase, strip edge-digit padding, fold interior homoglyphs, drop the rest.

    Two distinct impersonation attacks need different handling, and the
    same digit (`0` / `1`) is ambiguous between them:

    - **Padding**: appending or prepending digits to a reserved word —
      `admin99`, `flip2024`, `999admin`. Edge digit runs are stripped
      wholesale so the residue equals the reserved root.
    - **Homoglyphs**: substituting a letter-shaped digit interior to a
      word — `m0derator`, `flipc0mmons`. After edge stripping, remaining
      digits are folded via `_HOMOGLYPHS`; only `0` and `1` are credible
      letter-substitutes, so other interior digits fall through to the
      non-letter strip.

    Finally, anything still non-letter (hyphens, underscores, residual
    digits) is dropped so hyphenation variants like `flip-commons` fold
    to the same residue as the canonical entry.
    """
    s = s.lower()
    # Strip leading and trailing digit runs. lstrip/rstrip on a digit set
    # is exactly the "padding" semantic — runs anchored to either edge.
    s = s.strip("0123456789")
    s = s.translate(_HOMOGLYPHS)
    return "".join(c for c in s if c.isalpha())


def is_reserved(candidate: Username) -> bool:
    """Return True if *candidate* matches a reserved entry.

    Match rule: normalize both sides; reject if the normalized candidate
    *equals* any stem, any affix, or any `stem+affix` / `affix+stem`
    concatenation. Equality, not substring — otherwise a short stem like
    `flip` would block legitimate handles like `flipperjones`.
    """
    n = normalize(candidate)
    if n in STEMS or n in AFFIXES:
        return True
    return any(
        n == stem + affix or n == affix + stem for stem in STEMS for affix in AFFIXES
    )
