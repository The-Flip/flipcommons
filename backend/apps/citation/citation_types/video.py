"""The video citation type: platform roots with video children, plus movies.

A parentless video source with an ``identifier_key`` is a platform (YouTube)
— abstract, never cited directly; recognition resolves a video URL to a video
child under the platform root, exactly like web. A *schemeless* parentless
video is a **movie** — a work available through many channels, so it has no
canonical URL and is cited directly (the parentless-citable shape a standalone
book has). Either way a video *wants* a locator: the work identifies the
video, but the evidence lives at a moment in it, so the locator is an optional
**start time** — where to begin watching.

This module owns the timestamp grammar. It is the authoritative validator on
every write path (API mint, patch apply); schemes and the frontend only ever
see its structured output (seconds) or its canonical text form.

Accepted input forms (``parse_start_time``):

- bare seconds: ``95``
- colon forms: ``1:35`` (M:SS), ``1:02:03`` (H:MM:SS) — leading unit
  unbounded, trailing units 0–59, sloppy inner digits (``1:2:3``) tolerated
- unit form: ``1h2m3s``, ``95s``, ``2m`` — any subset in h→m→s order

Canonical stored form (``format_start_time``): leading unit unpadded, inner
units two-digit, hours segment only when ≥ 1 hour — ``0:57``, ``1:35``,
``12:05``, ``1:02:03``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from apps.citation.citation_types.citation_scheme_specs import SchemeSpec
from apps.citation.citation_types.citation_type_specs import (
    CitationTypeSpec,
    LocatorContract,
)
from apps.citation.citation_types.vocabulary import SourceType, StartSeconds

# The deliberate cap on a start time: 100 hours. Beyond it a bare-seconds
# input is far more likely a typo than a real start position; relaxing is a
# one-constant change, tightening would mean auditing stored locators.
MAX_START_TIME_SECONDS = 100 * 3600

# M:SS or H:MM:SS. Leading segment unbounded, later segments 1–2 digits
# (sloppy ``1:2:3`` normalizes rather than rejects); range-checked below.
_COLON_RE = re.compile(r"\A(\d+)(?::(\d{1,2}))?:(\d{1,2})\Z")
# Any subset of h/m/s in order, at least one (enforced below), values unbounded.
_UNITS_RE = re.compile(r"\A(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?\Z", re.IGNORECASE)
_BARE_SECONDS_RE = re.compile(r"\A\d+\Z")


def parse_start_time(raw: str) -> StartSeconds | None:
    """Parse a start-time locator input into whole seconds, or ``None``.

    The single grammar for every accepted form; surrounding whitespace is
    tolerated, anything else non-conforming is ``None`` — never a guess.
    """
    text = raw.strip()
    if not text:
        return None
    seconds = _parse_bare_or_colon(text)
    if seconds is None:
        seconds = _parse_units(text)
    if seconds is None or seconds > MAX_START_TIME_SECONDS:
        return None
    return seconds


def _parse_bare_or_colon(text: str) -> StartSeconds | None:
    if _BARE_SECONDS_RE.match(text):
        return int(text)
    m = _COLON_RE.match(text)
    if m is None:
        return None
    lead, mid, tail = m.group(1), m.group(2), m.group(3)
    if mid is None:
        minutes, secs = int(lead), int(tail)
        if secs > 59:
            return None
        return minutes * 60 + secs
    hours, minutes, secs = int(lead), int(mid), int(tail)
    if minutes > 59 or secs > 59:
        return None
    return hours * 3600 + minutes * 60 + secs


def _parse_units(text: str) -> StartSeconds | None:
    m = _UNITS_RE.match(text)
    if m is None or not any(m.groups()):
        return None
    hours, minutes, secs = (int(g) if g else 0 for g in m.groups())
    return hours * 3600 + minutes * 60 + secs


def format_start_time(seconds: StartSeconds) -> str:
    """Format whole *seconds* as the canonical human-readable start time."""
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def normalize_start_time(raw: str) -> str | None:
    """Validate + canonicalize a start-time locator, or ``None`` if invalid."""
    seconds = parse_start_time(raw)
    if seconds is None:
        return None
    return format_start_time(seconds)


@dataclass(frozen=True, slots=True)
class VideoSchemeSpec(SchemeSpec):
    """The contract a video-platform scheme implements.

    Adds no fields over :class:`SchemeSpec` — real platforms diverge on the
    time capabilities, so both stay optional. YouTube and Vimeo URLs can seek
    (``deep_link_template`` + ``start_seconds_source``); TikTok URLs cannot,
    and a video child without a jump URL still wants its timestamp locator —
    the reader sees the ``(1:35)`` text beside the plain video link and
    scrubs by hand. What must pair up is enforced by the conformance
    harness: a scheme that *extracts* start-time hints from URLs must also
    *build* them.

    A video scheme may only recognize URL shapes that are **guaranteed to be
    videos** (the type-homogeneity rule): recognition is syntactic, so a
    shape that can hold other media would mint wrong-typed children. TikTok
    qualifies because its paths discriminate (``/video/`` vs ``/photo/``);
    X's ``/status/`` does not, which is why X is a *web* scheme.

    The subclass is the registered per-type contract (``scheme_spec_type``)
    and nothing more: a video scheme declares itself one by constructing this
    type, so the registry's isinstance backstop catches a spec registered
    under the wrong type. It deliberately carries no fields and no behavior —
    even the URL start-time values are parsed framework-side through this
    type's ``locator.parse_value`` grammar, not here — so a scheme author
    sees only what they fill in.
    """


VIDEO = CitationTypeSpec(
    source_type=SourceType.VIDEO,
    flat_hierarchy=True,
    # A schemeless parentless video is a **movie** — a work available through
    # many channels, so it has no canonical URL and is cited directly (the
    # parentless-citable shape a standalone book has). A video root *with* an
    # ``identifier_key`` (a platform like YouTube) is still abstract, kept so
    # universally by ``CitationSource.is_abstract``, not by this field.
    schemeless_parentless_abstract=False,
    child_skips_locator=False,
    locator=LocatorContract(
        kind="timestamp",
        placeholder="e.g. 1:02:03",
        label="Start time",
        help="Where to begin watching — e.g. 1:02:03, 95, or 1h2m3s",
        display_prefix="starting at",
        normalize=normalize_start_time,
        parse_value=parse_start_time,
        format_value=format_start_time,
        invalid_message=(
            "Enter a start time like 1:02:03, 95, or 1h2m3s (where to start watching)."
        ),
    ),
    scheme_spec_type=VideoSchemeSpec,
)
