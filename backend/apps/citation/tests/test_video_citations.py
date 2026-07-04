"""Tests for video citations: the youtube scheme, recognition hints, deep links.

The grammar itself is covered by ``test_video_locators.py`` and the generic
scheme contract by ``schemes/test_conformance.py``; this file covers the
youtube scheme's platform-specific behavior and the read-side composition
(recognition ``locator_hint``, ``deep_linked_url``).
"""

import pytest

from apps.accounts.test_factories import default_actor
from apps.citation.citation_types import SCHEME_SPECS
from apps.citation.deep_links import deep_linked_url
from apps.citation.extractors import get_or_create_external_source, recognize_url
from apps.citation.test_factories import make_citation_link, make_citation_source

# The id used throughout (Rick Astley, "Never Gonna Give You Up").
VID = "dQw4w9WgXcQ"
CANONICAL = f"https://www.youtube.com/watch?v={VID}"

YOUTUBE = SCHEME_SPECS["youtube"]


@pytest.fixture
def youtube_root(db):
    return make_citation_source(
        name="YouTube", source_type="video", identifier_key="youtube"
    )


class TestStartSecondsHint:
    """``extract`` surfaces a pasted start time as structured seconds."""

    @pytest.mark.parametrize(
        ("url", "seconds"),
        [
            (f"{CANONICAL}&t=95", 95),
            (f"{CANONICAL}&t=95s", 95),
            (f"{CANONICAL}&t=1h2m3s", 3723),
            (f"https://youtu.be/{VID}?t=95", 95),
            (f"https://www.youtube.com/embed/{VID}?start=95", 95),
            (f"https://www.youtube.com/shorts/{VID}?t=2m", 120),
        ],
    )
    def test_start_time_params_extract(self, url, seconds):
        match = YOUTUBE.extract(url)
        assert match is not None
        assert match.identifier == VID
        assert match.start_seconds == seconds

    @pytest.mark.parametrize(
        "url",
        [
            CANONICAL,  # no param at all
            f"{CANONICAL}&t=0",  # "from the beginning" — not a hint
            f"{CANONICAL}&t=banana",  # malformed — abstain, don't guess
            f"https://youtu.be/{VID}?si=AbCdEf",  # unrelated param
        ],
    )
    def test_no_usable_hint_yields_none(self, url):
        match = YOUTUBE.extract(url)
        assert match is not None
        assert match.start_seconds is None


class TestRecognitionLocatorHint:
    """Recognition carries the hint as canonical locator text."""

    def test_pasted_start_time_becomes_locator_hint(self, youtube_root):
        rec = recognize_url(f"https://youtu.be/{VID}?t=95")
        assert rec is not None
        assert rec.locator_hint == "1:35"

    def test_no_start_time_means_empty_hint(self, youtube_root):
        rec = recognize_url(f"https://youtu.be/{VID}")
        assert rec is not None
        assert rec.locator_hint == ""


class TestVideoChildMinting:
    def test_scheme_children_mint_as_video(self, youtube_root):
        child = get_or_create_external_source(
            "youtube", VID, created_by=default_actor()
        )
        assert child.source_type == "video"
        assert child.parent_id == youtube_root.pk
        assert child.links.get().url == CANONICAL

    def test_video_child_wants_a_locator(self, youtube_root):
        child = get_or_create_external_source(
            "youtube", VID, created_by=default_actor()
        )
        # Unlike a web child, a video child does NOT skip the locator stage —
        # collecting the start time is the point of the video type.
        assert child.skip_locator is False


class TestDeepLinkedUrl:
    @pytest.fixture
    def video_child(self, youtube_root):
        child = make_citation_source(
            name=f"YouTube #{VID}",
            source_type="video",
            parent=youtube_root,
            identifier=VID,
        )
        make_citation_link(citation_source=child, link_type="reference", url=CANONICAL)
        return child

    def test_canonical_link_deep_links_to_the_locator(self, video_child):
        assert (
            deep_linked_url(video_child, "1:02:03", CANONICAL) == f"{CANONICAL}&t=3723s"
        )

    def test_no_locator_leaves_url_untouched(self, video_child):
        assert deep_linked_url(video_child, "", CANONICAL) == CANONICAL

    def test_non_canonical_link_untouched(self, video_child):
        # An archive snapshot (or any extra link) is never rewritten.
        archive = f"https://web.archive.org/web/2024/{CANONICAL}"
        assert deep_linked_url(video_child, "1:35", archive) == archive

    def test_web_child_untouched(self, db):
        root = make_citation_source(
            name="IPDB", source_type="web", identifier_key="ipdb"
        )
        child = make_citation_source(
            name="IPDB #4443", source_type="web", parent=root, identifier="4443"
        )
        url = "https://www.ipdb.org/machine.cgi?id=4443"
        assert deep_linked_url(child, "Notes section", url) == url

    def test_rootless_source_untouched(self, db):
        book = make_citation_source(name="A Book", source_type="book")
        assert deep_linked_url(book, "p. 42", "https://x.example/") == (
            "https://x.example/"
        )

    def test_unparseable_locator_untouched(self, video_child):
        # Defense in depth: write paths validate video locators, but a
        # pre-validation row must degrade to the plain link, not crash.
        assert deep_linked_url(video_child, "p. 42", CANONICAL) == CANONICAL
