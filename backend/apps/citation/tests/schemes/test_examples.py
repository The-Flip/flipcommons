"""The data-driven scheme example harness.

Each scheme declares a ``SchemeExamples`` table in its ``test_<scheme>`` module
(real-platform URL shapes: valid, invalid look-alikes, start-time cases). This
harness collects them through the explicit ``SCHEME_EXAMPLES`` registry below —
greppable like the production ``_SCHEMES`` tuple — and parametrizes over every
declared case, so a scheme's platform coverage is *data*, not a hand-written
test module.

Division of labor: ``test_conformance`` owns the generic invariants shared code
relies on (round-trip, host anchoring, junk rejection); this owns the
platform-specific shapes only a scheme's author knows. Pure — no database.
"""

import pytest

from apps.citation.citation_types import SCHEME_SPECS, SchemeSpec

from . import test_ipdb, test_opdb, test_tiktok, test_vimeo, test_x, test_youtube
from .example_data import SchemeExamples, SchemeUrlCase, StartTimeCase

# Explicit examples registry — one line per scheme, mirroring the production
# _SCHEMES registration. The guard below holds it to exactly the registered
# scheme set: every scheme declares an example table, and no entry names an
# unregistered scheme.
SCHEME_EXAMPLES: dict[str, SchemeExamples] = {
    "ipdb": test_ipdb.EXAMPLES,
    "opdb": test_opdb.EXAMPLES,
    "youtube": test_youtube.EXAMPLES,
    "vimeo": test_vimeo.EXAMPLES,
    "tiktok": test_tiktok.EXAMPLES,
    "x": test_x.EXAMPLES,
}

assert SCHEME_EXAMPLES.keys() == set(SCHEME_SPECS), (
    "SCHEME_EXAMPLES must cover exactly the registered schemes; "
    f"missing={sorted(set(SCHEME_SPECS) - SCHEME_EXAMPLES.keys())}, "
    f"unregistered={sorted(SCHEME_EXAMPLES.keys() - set(SCHEME_SPECS))}"
)


def _spec(key: str) -> SchemeSpec:
    return SCHEME_SPECS[key]


# Flattened tables, built once at import; the paired ids lists give per-URL
# test names. Valid/invalid rows are named SchemeUrlCase pairs; start-time rows
# stay a plain (scheme_key, StartTimeCase) tuple — StartTimeCase already names
# the payload.
_VALID_CASES: list[SchemeUrlCase] = [
    SchemeUrlCase(key, url)
    for key, ex in SCHEME_EXAMPLES.items()
    for url in ex.valid_urls
]
_INVALID_CASES: list[SchemeUrlCase] = [
    SchemeUrlCase(key, url)
    for key, ex in SCHEME_EXAMPLES.items()
    for url in ex.invalid_urls
]
_START_TIME_CASES: list[tuple[str, StartTimeCase]] = [
    (key, case) for key, ex in SCHEME_EXAMPLES.items() for case in ex.start_time_cases
]


@pytest.mark.parametrize(
    ("key", "url"),
    _VALID_CASES,
    ids=[f"{c.scheme_key}-{c.url}" for c in _VALID_CASES],
)
def test_valid_url_normalizes_to_the_example_identifier(key: str, url: str) -> None:
    """Every declared valid shape resolves to the scheme's example identifier."""
    spec = _spec(key)
    assert spec.normalize(url) == spec.example_identifier


@pytest.mark.parametrize(
    ("key", "url"),
    _INVALID_CASES,
    ids=[f"{c.scheme_key}-{c.url}" for c in _INVALID_CASES],
)
def test_invalid_url_is_rejected(key: str, url: str) -> None:
    """Every declared look-alike / near-miss normalizes to ``None``."""
    assert _spec(key).normalize(url) is None


@pytest.mark.parametrize(
    ("key", "case"),
    _START_TIME_CASES,
    ids=[f"{key}-{case.url}" for key, case in _START_TIME_CASES],
)
def test_start_time_case_extracts_expected_seconds(
    key: str, case: StartTimeCase
) -> None:
    """A recognized URL surfaces the declared ``start_seconds`` (or ``None``)."""
    match = _spec(key).extract(case.url)
    assert match is not None, f"{key}: example URL not recognized: {case.url}"
    assert match.start_seconds == case.seconds
