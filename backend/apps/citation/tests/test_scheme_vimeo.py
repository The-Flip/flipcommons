"""Example-based tests for the Vimeo scheme's real URL shapes.

The generic invariants (round-trip, host anchoring, junk ids) are covered by
the conformance harness; this pins Vimeo's platform-specific shapes — the
fragment-borne start time and the unlisted-hash path — as examples. Pure — no
database.
"""

import pytest

from apps.citation.citation_types import SCHEME_SPECS

VID = "347119375"

vimeo = SCHEME_SPECS["vimeo"]


class TestVimeoNormalize:
    """``normalize`` accepts watch/embed URL shapes or a bare id."""

    @pytest.mark.parametrize(
        "raw",
        [
            VID,  # bare id
            f"https://vimeo.com/{VID}",
            f"https://www.vimeo.com/{VID}",
            f"http://vimeo.com/{VID}",
            f"https://vimeo.com/{VID}/",  # single trailing slash is tolerated
            f"https://vimeo.com/{VID}?share=copy",
            f"https://vimeo.com/{VID}#t=90s",
            # Unlisted-access hash: an access token, not identity — dropped.
            f"https://vimeo.com/{VID}/d0e9b81c05",
            f"https://vimeo.com/{VID}/d0e9b81c05?share=copy",
            # Embed player on its own subdomain; the hash rides as ?h= there.
            f"https://player.vimeo.com/video/{VID}",
            f"https://player.vimeo.com/video/{VID}?h=d0e9b81c05",
        ],
    )
    def test_every_shape_normalizes_to_the_id(self, raw):
        assert vimeo.normalize(raw) == VID

    @pytest.mark.parametrize(
        "raw",
        [
            "abc123",  # not numeric
            f"https://notvimeo.com/{VID}",  # look-alike host
            f"https://vimeo.com.evil.com/{VID}",  # host as a prefix label
            f"https://vimeo.com/user{VID}",  # profile, not a video
            f"https://vimeo.com/{VID}/review",  # non-hex path tail is not a hash
            f"https://vimeo.com/{VID}/d0e9b81c05/extra",  # extra path segment
            f"https://vimeo.com/channels/staffpicks/{VID}",  # legacy browse shape
            f"https://player.vimeo.com/{VID}",  # embed shape needs /video/
            f"https://example.com/{VID}",  # bare id buried in a foreign URL
        ],
    )
    def test_invalid_inputs_return_none(self, raw):
        assert vimeo.normalize(raw) is None

    def test_canonical_url_is_the_bare_watch_page(self):
        assert vimeo.canonical_url(VID) == f"https://vimeo.com/{VID}"


class TestVimeoStartSeconds:
    """The start time rides in the URL fragment, in unit or bare-seconds form."""

    @pytest.mark.parametrize(
        ("url", "seconds"),
        [
            (f"https://vimeo.com/{VID}#t=90s", 90),
            (f"https://vimeo.com/{VID}#t=1m30s", 90),
            (f"https://vimeo.com/{VID}#t=1h2m3s", 3723),
            (f"https://vimeo.com/{VID}#t=95", 95),
            (f"https://player.vimeo.com/video/{VID}?h=abc123#t=2m", 120),
        ],
    )
    def test_fragment_start_time_is_extracted(self, url, seconds):
        match = vimeo.extract(url)
        assert match is not None
        assert match.start_seconds == seconds

    @pytest.mark.parametrize(
        "url",
        [
            f"https://vimeo.com/{VID}",  # no fragment
            f"https://vimeo.com/{VID}#t=0s",  # zero means "from the beginning"
            f"https://vimeo.com/{VID}#t=junk",  # malformed abstains
            f"https://vimeo.com/{VID}?t=90s",  # query t= is not Vimeo's syntax
        ],
    )
    def test_no_usable_hint_yields_none(self, url):
        match = vimeo.extract(url)
        assert match is not None
        assert match.start_seconds is None

    def test_deep_link_uses_the_fragment_syntax(self):
        assert vimeo.deep_link is not None
        assert vimeo.deep_link(VID, 3723) == f"https://vimeo.com/{VID}#t=3723s"
