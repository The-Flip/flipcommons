"""X (Twitter) scheme tests: its declared example table plus identity bespoke.

X is the multi-host stress case: two full host families (x.com and legacy
twitter.com) collapse to one child per status id, and the vanity handle is
excluded from identity so the canonical URL survives renames. It is a **web**
scheme — a /status/ URL entails nothing about the post's media. ``EXAMPLES``
pins the recognized shapes; the bespoke tests cover the handle-free canonical,
the two-host collapse, the web owning type and the absent time capabilities.
Generic invariants live in ``test_conformance``. Pure — no database.
"""

from apps.citation.citation_types import SCHEME_SPECS, SourceType

from .example_data import SchemeExamples

SID = "1585341984679469056"

x = SCHEME_SPECS["x"]

EXAMPLES = SchemeExamples(
    example_identifier=SID,
    valid_urls=(
        f"https://x.com/PinballNews/status/{SID}",
        f"https://twitter.com/PinballNews/status/{SID}",
        f"https://www.x.com/PinballNews/status/{SID}",
        f"https://www.twitter.com/PinballNews/status/{SID}",
        f"https://mobile.twitter.com/PinballNews/status/{SID}",
        f"http://twitter.com/PinballNews/status/{SID}",
        f"https://x.com/i/web/status/{SID}",  # handle-free web shape
        f"https://twitter.com/statuses/{SID}",  # legacy path form
        # Media tails and params on pasted URLs are tolerated.
        f"https://x.com/PinballNews/status/{SID}/video/1",
        f"https://x.com/PinballNews/status/{SID}/photo/1",
        f"https://x.com/PinballNews/status/{SID}?s=20&t=abc",
        f"https://x.com/PinballNews/status/{SID}#m",
    ),
    invalid_urls=(
        f"https://notx.com/user/status/{SID}",  # look-alike host
        f"https://x.com.evil.com/user/status/{SID}",  # host as a prefix label
        f"https://x.com/user/status/{SID}abc",  # id must end at a boundary
        "https://x.com/PinballNews",  # profile, not a post
        f"https://x.com/i/lists/{SID}",  # a list, not a post
        f"https://x.com/a_way_too_long_username/status/{SID}",  # handle >15 chars
        f"https://example.com/status/{SID}",  # wrong site
    ),
)


def test_canonical_url_is_the_handle_free_form() -> None:
    # Rename-stable: no vanity handle baked into the stored link.
    assert x.canonical_url(SID) == f"https://x.com/i/status/{SID}"


def test_both_host_families_collapse_to_one_identifier() -> None:
    via_x = x.normalize(f"https://x.com/PinballNews/status/{SID}")
    via_twitter = x.normalize(f"https://twitter.com/PinballNews/status/{SID}")
    assert via_x == via_twitter == SID


def test_children_mint_as_web_pages() -> None:
    # The type-homogeneity rule: a /status/ URL may hold text, photos or video,
    # so the scheme's owning type is web — a post cites as a whole page.
    assert x.source_type is SourceType.WEB


def test_no_time_capabilities() -> None:
    # X URLs have no seek parameter — the scheme honestly declares neither.
    assert x.deep_link is None
    assert x.start_seconds_from_url is None
