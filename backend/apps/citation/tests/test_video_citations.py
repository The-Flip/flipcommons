"""Tests for video citations: recognition hints and deep links, DB-side.

The grammar itself is covered by ``test_video_locators.py``, the generic
scheme contract by ``schemes/test_conformance.py`` and the youtube URL/hint
shapes by its example table in ``schemes/test_youtube.py``; this file covers
the read-side composition against real rows (recognition ``locator_hint``,
``deep_linked_url``).
"""

import pytest

from apps.accounts.test_factories import default_actor
from apps.citation.deep_links import deep_linked_url
from apps.citation.extractors import get_or_create_external_source, recognize_url
from apps.citation.test_factories import make_citation_link, make_citation_source

# The id used throughout (Rick Astley, "Never Gonna Give You Up").
VID = "dQw4w9WgXcQ"
CANONICAL = f"https://www.youtube.com/watch?v={VID}"


@pytest.fixture
def youtube_root(db):
    return make_citation_source(
        name="YouTube", source_type="video", identifier_key="youtube"
    )


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
