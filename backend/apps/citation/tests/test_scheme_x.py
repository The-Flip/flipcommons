"""Example-based tests for the X (Twitter) scheme's real URL shapes.

X is the multi-host stress case: two full host families (x.com and legacy
twitter.com) collapse to one child per status id, and the vanity handle in
the path is excluded from identity so the canonical URL survives renames.
It is a **web** scheme — a /status/ URL entails nothing about the post's
media, so posts mint as web pages, never as videos. The generic invariants
live in the conformance harness. Pure — no database.
"""

import pytest

from apps.citation.citation_types import SCHEME_SPECS, SourceType

SID = "1585341984679469056"

x = SCHEME_SPECS["x"]


class TestXNormalize:
    """``normalize`` accepts both host families or a bare status id."""

    @pytest.mark.parametrize(
        "raw",
        [
            SID,  # bare status id
            f"https://x.com/PinballNews/status/{SID}",
            f"https://twitter.com/PinballNews/status/{SID}",
            f"https://www.x.com/PinballNews/status/{SID}",
            f"https://www.twitter.com/PinballNews/status/{SID}",
            f"https://mobile.twitter.com/PinballNews/status/{SID}",
            f"http://twitter.com/PinballNews/status/{SID}",
            # Handle-free shapes — the rename-stable forms.
            f"https://x.com/i/status/{SID}",
            f"https://x.com/i/web/status/{SID}",
            f"https://twitter.com/statuses/{SID}",  # legacy path form
            # Media tails and params on pasted URLs are tolerated.
            f"https://x.com/PinballNews/status/{SID}/video/1",
            f"https://x.com/PinballNews/status/{SID}/photo/1",
            f"https://x.com/PinballNews/status/{SID}?s=20&t=abc",
            f"https://x.com/PinballNews/status/{SID}#m",
        ],
    )
    def test_every_shape_normalizes_to_the_status_id(self, raw):
        assert x.normalize(raw) == SID

    @pytest.mark.parametrize(
        "raw",
        [
            f"https://notx.com/user/status/{SID}",  # look-alike host
            f"https://x.com.evil.com/user/status/{SID}",  # host as a prefix label
            f"https://x.com/user/status/{SID}abc",  # id must end at a boundary
            "https://x.com/PinballNews",  # profile, not a post
            f"https://x.com/i/lists/{SID}",  # a list, not a post
            f"https://x.com/a_way_too_long_username/status/{SID}",  # >15 chars
            f"https://example.com/status/{SID}",  # wrong site
        ],
    )
    def test_invalid_inputs_return_none(self, raw):
        assert x.normalize(raw) is None

    def test_canonical_url_is_the_handle_free_form(self):
        # Rename-stable: no vanity handle baked into the stored link.
        assert x.canonical_url(SID) == f"https://x.com/i/status/{SID}"

    def test_both_host_families_collapse_to_one_identifier(self):
        via_x = x.normalize(f"https://x.com/PinballNews/status/{SID}")
        via_twitter = x.normalize(f"https://twitter.com/PinballNews/status/{SID}")
        assert via_x == via_twitter == SID

    def test_children_mint_as_web_pages(self):
        # The type-homogeneity rule: a /status/ URL may hold text, photos or
        # video, so the scheme's owning type is web — a post cites as a whole
        # page (skip_locator), never as a video with a timestamp prompt.
        assert x.source_type is SourceType.WEB

    def test_no_time_capabilities(self):
        # X URLs have no seek parameter — the scheme honestly declares
        # neither capability instead of faking a jump URL.
        assert x.deep_link is None
        assert x.start_seconds_from_url is None
