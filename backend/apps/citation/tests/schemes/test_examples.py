"""The data-driven scheme example harness.

Each scheme declares a ``SchemeExamples`` table in its ``test_<scheme>`` module
(real-platform URL shapes: valid, invalid look-alikes, start-time cases),
collected in the shared ``example_registry``. This harness parametrizes over
every declared case, so a scheme's platform coverage is *data*, not a
hand-written test module.

Division of labor: ``test_conformance`` owns the generic invariants shared code
relies on (round-trip, host anchoring, junk rejection); this owns the
platform-specific shapes only a scheme's author knows. Pure — no database.
"""

import pytest

from apps.citation.citation_types import SCHEME_SPECS, SchemeSpec

from .example_data import SchemeUrlCase, StartTimeCase
from .example_registry import SCHEME_EXAMPLES


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
    assert _spec(key).normalize(url) == SCHEME_EXAMPLES[key].example_identifier


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


@pytest.mark.parametrize("key", list(SCHEME_EXAMPLES))
def test_canonical_url_builds_exactly_the_declared_form(key: str) -> None:
    """The canonical URL is the exact declared string, not just a round-tripper."""
    ex = SCHEME_EXAMPLES[key]
    assert _spec(key).canonical_url(ex.example_identifier) == ex.canonical_url


@pytest.mark.parametrize("key", list(SCHEME_EXAMPLES))
def test_deep_link_case_matches_the_capability_and_its_output(key: str) -> None:
    """A ``deep_link`` builder and a declared example imply each other.

    A scheme that can seek must pin its platform's seek syntax as data; a
    declared case on a scheme that can't seek is a stale table.
    """
    ex, spec = SCHEME_EXAMPLES[key], _spec(key)
    if spec.deep_link_template is None:
        assert ex.deep_link_case is None, f"{key}: deep_link_case but no template"
    else:
        assert ex.deep_link_case is not None, f"{key}: template but no deep_link_case"
        built = spec.deep_link(ex.example_identifier, ex.deep_link_case.seconds)
        assert built == ex.deep_link_case.url
