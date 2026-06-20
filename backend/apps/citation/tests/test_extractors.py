"""Tests for the identifier-scheme extractors (``EXTRACTORS`` registry).

Focused on YouTube, whose video id is reachable through many URL shapes —
the regex collapsing them all to one canonical 11-char id is the risky part.
"""

import pytest

from apps.citation.extractors import (
    EXTRACTORS,
    get_or_create_external_source,
    recognize_url,
)
from apps.citation.models import (
    CitationSource,
    CitationSourceLink,
    CitationSourceRootDomain,
)

# A real-looking 11-char video id (Rick Astley, "Never Gonna Give You Up").
VID = "dQw4w9WgXcQ"


@pytest.fixture
def youtube_root(db):
    return CitationSource.objects.create(
        name="YouTube", source_type="web", identifier_key="youtube"
    )


class TestYouTubeNormalize:
    """``normalize`` accepts any URL shape or a bare id, returning the id."""

    yt = EXTRACTORS["youtube"]

    @pytest.mark.parametrize(
        "raw",
        [
            VID,  # bare id
            f"https://www.youtube.com/watch?v={VID}",
            f"https://youtube.com/watch?v={VID}",
            f"http://www.youtube.com/watch?v={VID}",
            f"https://m.youtube.com/watch?v={VID}",
            f"https://youtu.be/{VID}",
            f"https://www.youtube.com/shorts/{VID}",
            f"https://www.youtube.com/embed/{VID}",
            f"https://www.youtube.com/live/{VID}",
            # Trailing/extra params are ignored.
            f"https://youtu.be/{VID}?si=AbCdEf",
            f"https://www.youtube.com/watch?v={VID}&t=42s",
            f"https://www.youtube.com/watch?list=PL123&v={VID}",
            f"https://www.youtube.com/shorts/{VID}?feature=share",
        ],
    )
    def test_every_shape_normalizes_to_the_id(self, raw):
        assert self.yt.normalize(raw) == VID

    @pytest.mark.parametrize(
        "raw",
        [
            "dQw4w9WgXc",  # 10 chars — too short for a bare id
            "dQw4w9WgXcQX",  # 12 chars — too long
            f"https://youtu.be/{VID}X",  # 12-char URL id must not truncate to 11
            f"https://www.youtube.com/watch?v={VID}X",  # ditto, watch shape
            f"https://notyoutube.com/watch?v={VID}",  # look-alike host
            f"https://www.notyoutube.com/watch?v={VID}",  # look-alike host + www
            f"https://youtube.com.evil.com/watch?v={VID}",  # host as a prefix label
            "https://www.ipdb.org/machine.cgi?id=4443",  # wrong site
            "https://example.com/dQw4w9WgXcQ",  # bare id buried in a foreign URL
            "not a url or id",
        ],
    )
    def test_invalid_inputs_return_none(self, raw):
        assert self.yt.normalize(raw) is None

    def test_build_url_is_canonical_watch(self):
        assert self.yt.build_url(VID) == f"https://www.youtube.com/watch?v={VID}"


class TestYouTubeRecognition:
    """``recognize_url`` resolves any YouTube URL to the seeded root."""

    def test_url_recognized_no_child(self, youtube_root):
        rec = recognize_url(f"https://youtu.be/{VID}")
        assert rec is not None
        assert rec.parent_id == youtube_root.id
        assert rec.identifier == VID
        assert rec.child is None

    def test_url_recognized_with_existing_child(self, youtube_root):
        child = CitationSource.objects.create(
            name=f"YouTube #{VID}",
            source_type="web",
            parent=youtube_root,
            identifier=VID,
        )
        rec = recognize_url(f"https://www.youtube.com/shorts/{VID}")
        assert rec is not None
        assert rec.child is not None
        assert rec.child.id == child.id
        assert rec.identifier == VID

    def test_no_root_seeded_yields_no_recognition(self, db):
        assert recognize_url(f"https://youtu.be/{VID}") is None


class TestRootDomainRecognition:
    """``recognize_url`` step 3: resolve a host to its root by longest suffix."""

    def _root(self, name: str, host: str) -> CitationSource:
        root = CitationSource.objects.create(name=name, source_type="web")
        CitationSourceRootDomain.objects.create(source=root, host=host)
        return root

    def test_subdomain_collapses_to_registrable_root(self, db):
        ap = self._root("American Pinball", "american-pinball.com")
        rec = recognize_url("http://s4.american-pinball.com/games/gtf/manual.pdf")
        assert rec is not None
        assert rec.parent_id == ap.id
        assert rec.child is None
        assert rec.identifier is None

    def test_most_specific_root_wins(self, db):
        self._root("Kineticist", "kineticist.com")
        twip = self._root("TWiP", "twip.kineticist.com")
        rec = recognize_url("https://twip.kineticist.com/some-article")
        assert rec is not None
        assert rec.parent_id == twip.id

    def test_subdomain_falls_back_to_parent_when_no_specific_root(self, db):
        kineticist = self._root("Kineticist", "kineticist.com")
        rec = recognize_url("https://twip.kineticist.com/some-article")
        assert rec is not None
        assert rec.parent_id == kineticist.id

    def test_deeper_subdomain_resolves_to_nearest_root(self, db):
        ap = self._root("American Pinball", "american-pinball.com")
        rec = recognize_url("https://cdn.assets.american-pinball.com/logo.png")
        assert rec is not None
        assert rec.parent_id == ap.id

    def test_www_prefixed_input_matches(self, db):
        ap = self._root("American Pinball", "american-pinball.com")
        rec = recognize_url("https://www.american-pinball.com/about")
        assert rec is not None
        assert rec.parent_id == ap.id

    def test_lookalike_host_does_not_match(self, db):
        self._root("American Pinball", "american-pinball.com")
        assert recognize_url("https://evil-american-pinball.com/x") is None

    def test_unknown_host_no_recognition(self, db):
        self._root("American Pinball", "american-pinball.com")
        assert recognize_url("https://example.com/x") is None

    def test_root_domain_on_child_is_ignored(self, db):
        # The source__parent__isnull filter is defense-in-depth for the clean()
        # root-only rule: a domain attached to a child via a bypass (raw create)
        # never drives recognition.
        parent = CitationSource.objects.create(name="Parent", source_type="web")
        child = CitationSource.objects.create(
            name="Child", source_type="web", parent=parent
        )
        CitationSourceRootDomain.objects.create(source=child, host="child.example.com")
        assert recognize_url("https://child.example.com/page") is None


class TestYouTubeGetOrCreate:
    """``get_or_create_external_source`` is idempotent and builds canonical URLs."""

    def test_creates_child_with_canonical_link(self, youtube_root):
        child = get_or_create_external_source("youtube", f"https://youtu.be/{VID}")
        assert child.parent_id == youtube_root.id
        assert child.identifier == VID
        link = CitationSourceLink.objects.get(citation_source=child)
        assert link.url == f"https://www.youtube.com/watch?v={VID}"

    def test_idempotent_across_url_shapes(self, youtube_root):
        first = get_or_create_external_source("youtube", f"https://youtu.be/{VID}")
        second = get_or_create_external_source(
            "youtube", f"https://www.youtube.com/watch?v={VID}&t=10s"
        )
        assert first.id == second.id
