"""Data types for the scheme example harness.

Test-side support: a scheme's platform-specific URL examples are *data*, not
hand-written test code. These types hold that data; the harness
(``test_examples``) drives it and each ``test_<scheme>`` module declares it.
Deliberately outside the production spec — examples are test fixtures and never
ship on ``SchemeSpec``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

from apps.citation.citation_types import StartSeconds


class StartTimeCase(NamedTuple):
    """One start-time extraction example: a URL and the seconds it should yield.

    ``seconds`` is ``None`` when the URL is recognized but carries no usable
    start-time hint (``t=0``, a malformed value, or no time param at all) — the
    harness asserts ``extract(url).start_seconds`` equals it either way.
    """

    url: str
    seconds: StartSeconds | None


class SchemeUrlCase(NamedTuple):
    """A URL to check against a scheme — one row of a valid or invalid list.

    Names the ``(scheme_key, url)`` pair the harness flattens its per-scheme
    tables into, so the ``tuple[str, str]`` positions aren't ambiguous where the
    parametrized cases are built.
    """

    scheme_key: str
    url: str


@dataclass(frozen=True, slots=True)
class SchemeExamples:
    """A scheme's real-platform URL examples, declared in its test module.

    - ``valid_urls``: alternate URL shapes of the scheme's ``example_identifier``
      — each must ``normalize`` to it. The bare id and canonical URL round-trip
      is already covered by the conformance harness, so these are the platform's
      *other* shapes (mobile, embed, trailing params, ...).
    - ``invalid_urls``: look-alikes and near-misses that must ``normalize`` to
      ``None`` (wrong host, host-as-prefix label, an id past its boundary, a
      foreign path that merely contains the id).
    - ``start_time_cases``: URL → extracted ``start_seconds`` (or ``None`` for a
      recognized URL with no usable hint). Empty for schemes with no time axis.
    """

    valid_urls: tuple[str, ...] = ()
    invalid_urls: tuple[str, ...] = ()
    start_time_cases: tuple[StartTimeCase, ...] = ()
