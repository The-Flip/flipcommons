"""Tests for the identifier-scheme extractors (``EXTRACTORS`` registry).

Focused on YouTube, whose video id is reachable through many URL shapes —
the regex collapsing them all to one canonical 11-char id is the risky part.
"""

import pytest
from django.core.exceptions import ValidationError

from apps.accounts.test_factories import default_actor
from apps.citation.extractors import (
    EXTRACTORS,
    create_web_child,
    get_or_create_external_source,
    get_or_create_scheme_child,
    get_or_create_web_source,
    recognize_url,
)
from apps.citation.models import (
    CitationSource,
    CitationSourceLink,
    CitationSourceRootDomain,
)
from apps.citation.test_factories import (
    make_citation_link,
    make_citation_root_domain,
    make_citation_source,
)

# A real-looking 11-char video id (Rick Astley, "Never Gonna Give You Up").
VID = "dQw4w9WgXcQ"


@pytest.fixture
def youtube_root(db):
    return make_citation_source(
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
        child = make_citation_source(
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

    def test_extractor_match_without_scheme_root_falls_through_to_host(self, db):
        # Pins the extractor recognizer's continue-not-return behavior: the URL
        # matches the youtube pattern, but with no youtube *scheme* root seeded
        # the extractor recognizer abstains rather than returning None, so a
        # seeded youtube.com recognition host still resolves it (parent only, no
        # identifier). A flatten that returned at the first pattern hit would
        # regress this to None.
        host_root = make_citation_source(name="YouTube (web root)", source_type="web")
        make_citation_root_domain(source=host_root, host="youtube.com")
        rec = recognize_url(f"https://www.youtube.com/watch?v={VID}")
        assert rec is not None
        assert rec.parent_id == host_root.id
        assert rec.identifier is None
        assert rec.child is None


class TestRootDomainRecognition:
    """``recognize_url`` resolves a host to its root by longest label suffix.

    An asset subdomain collapses to its registrable root, while a deliberately
    seeded more-specific host still wins over its parent for its own subtree.
    """

    def _root(self, name: str, host: str) -> CitationSource:
        root = make_citation_source(name=name, source_type="web")
        make_citation_root_domain(source=root, host=host)
        return root

    def test_subdomain_resolves_to_registrable_root(self, db):
        ap = self._root("American Pinball", "american-pinball.com")
        rec = recognize_url("http://s4.american-pinball.com/games/gtf/manual.pdf")
        assert rec is not None
        assert rec.parent_id == ap.id

    def test_most_specific_host_wins(self, db):
        # twip.kineticist.com is itself a seeded host → it beats its parent
        # kineticist.com for its own subtree (longest label-boundary suffix).
        self._root("Kineticist", "kineticist.com")
        twip = self._root("TWiP", "twip.kineticist.com")
        rec = recognize_url("https://twip.kineticist.com/some-article")
        assert rec is not None
        assert rec.parent_id == twip.id

    def test_subdomain_resolves_to_parent_root(self, db):
        # No twip.* root seeded → the subdomain falls to its parent domain.
        kin = self._root("Kineticist", "kineticist.com")
        rec = recognize_url("https://twip.kineticist.com/some-article")
        assert rec is not None
        assert rec.parent_id == kin.id

    def test_deeper_subdomain_resolves_to_nearest_root(self, db):
        ap = self._root("American Pinball", "american-pinball.com")
        rec = recognize_url("https://cdn.assets.american-pinball.com/logo.png")
        assert rec is not None
        assert rec.parent_id == ap.id

    def test_public_suffix_cannot_be_declared_so_no_overmatch(self, db):
        # Ties the clean() guard to suffix matching: longest-suffix matching
        # would let a bare public-suffix host swallow every site beneath it — but
        # clean() forbids declaring one, so that root can't exist. Declaring "co.uk"
        # is rejected, and an unrelated *.co.uk cite stays unrecognized.
        root = make_citation_source(name="Bad", source_type="web")
        # Attribute it so full_clean's only complaint is the public-suffix host.
        with pytest.raises(ValidationError):
            CitationSourceRootDomain(
                source=root,
                host="co.uk",
                created_by=default_actor(),
                updated_by=default_actor(),
            ).full_clean()
        assert recognize_url("https://example.co.uk/page") is None

    def test_www_prefixed_input_matches(self, db):
        ap = self._root("American Pinball", "american-pinball.com")
        rec = recognize_url("https://www.american-pinball.com/about")
        assert rec is not None
        assert rec.parent_id == ap.id

    @pytest.mark.parametrize(
        "url",
        [
            # Empty label: normalizes to .american-pinball.com, whose ancestor
            # suffix is the seeded american-pinball.com — must NOT match.
            "https://www..american-pinball.com/manual.pdf",
            "https://foo_bar.american-pinball.com/x",  # underscore label
            # Too malformed for urlparse itself (unterminated IPv6 bracket) — it
            # raises ValueError; recognition must abstain, not propagate it.
            "https://[::1/american-pinball.com",
        ],
    )
    def test_malformed_host_is_not_recognized(self, db, url):
        # A malformed host can still produce a valid ancestor suffix; the
        # is_dns_host gate makes recognition abstain rather than claim a match a
        # read surface (/search/) would then surface as a confident page.
        self._root("American Pinball", "american-pinball.com")
        assert recognize_url(url) is None

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
        parent = make_citation_source(name="Parent", source_type="web")
        child = make_citation_source(name="Child", source_type="web", parent=parent)
        make_citation_root_domain(source=child, host="child.example.com")
        assert recognize_url("https://child.example.com/page") is None


class TestCreateWebChild:
    """The shared web-child leaf: validated, attributed, atomic."""

    @pytest.fixture
    def root(self, db):
        return make_citation_source(name="Kineticist", source_type="web")

    def test_mints_validated_child_and_reference_link(self, root):
        child = create_web_child(
            root.pk, "https://kineticist.com/article", created_by=default_actor()
        )
        assert child.parent_id == root.pk
        assert child.source_type == "web"
        link = child.links.get()
        assert link.url == "https://kineticist.com/article"
        assert link.link_type == "reference"

    def test_rejects_a_malformed_url_and_mints_nothing(self, root):
        # The link's URLField validates only in full_clean — the leaf's whole
        # point (closing the .objects.create bypass). Atomic: no orphaned child.
        with pytest.raises(ValidationError):
            create_web_child(root.pk, "not a url", created_by=default_actor())
        assert not CitationSource.objects.children().exists()

    def test_attribution_follows_created_by(self, root, user):
        attributed = create_web_child(
            root.pk, "https://kineticist.com/a", created_by=user.actor
        )
        assert attributed.created_by_id == user.actor_id
        assert attributed.links.get().created_by_id == user.actor_id


class TestGetOrCreateSchemeChild:
    """The shared scheme-child leaf: one name rule, idempotent, attributed."""

    @pytest.fixture
    def root(self, db):
        return make_citation_source(
            name="IPDB", source_type="web", identifier_key="ipdb"
        )

    def test_mints_named_child_with_canonical_link(self, root):
        child = get_or_create_scheme_child(root, "4443", created_by=default_actor())
        assert child.name == "IPDB #4443"
        assert child.identifier == "4443"
        link = child.links.get()
        assert link.url == "https://www.ipdb.org/machine.cgi?id=4443"
        assert link.link_type == "reference"

    def test_reuses_on_recite_across_url_shapes(self, root):
        first = get_or_create_scheme_child(root, "4443", created_by=default_actor())
        second = get_or_create_scheme_child(
            root, "https://www.ipdb.org/machine.cgi?id=4443", created_by=default_actor()
        )
        assert first.pk == second.pk
        assert first.links.count() == 1

    def test_rejects_an_invalid_identifier(self, root):
        with pytest.raises(ValueError, match="Invalid ipdb identifier"):
            get_or_create_scheme_child(root, "not-an-id", created_by=default_actor())

    def test_rejects_a_root_without_a_scheme(self, db):
        plain = make_citation_source(name="No scheme", source_type="web")
        with pytest.raises(ValueError, match="no known identifier scheme"):
            get_or_create_scheme_child(plain, "4443", created_by=default_actor())

    def test_rejects_an_over_long_identifier(self, root):
        # The ``\d+`` id regex has no length cap, so an over-long identifier must
        # be caught by field validation, not silently stored or DB-errored.
        with pytest.raises(ValidationError):
            get_or_create_scheme_child(root, "1" * 250, created_by=default_actor())
        assert not CitationSource.objects.children().exists()

    def test_attribution_follows_created_by(self, root, user):
        child = get_or_create_scheme_child(root, "4443", created_by=user.actor)
        assert child.created_by_id == user.actor_id
        assert child.links.get().created_by_id == user.actor_id

    def test_external_source_helper_resolves_the_same_child(self, root):
        # The patch helper (scheme→root lookup) and the leaf mint one child —
        # convergence on a single scheme-child home.
        via_helper = get_or_create_external_source(
            "ipdb", "4443", created_by=default_actor()
        )
        via_leaf = get_or_create_scheme_child(root, "4443", created_by=default_actor())
        assert via_helper.pk == via_leaf.pk


class TestYouTubeGetOrCreate:
    """``get_or_create_external_source`` is idempotent and builds canonical URLs."""

    def test_creates_child_with_canonical_link(self, youtube_root):
        child = get_or_create_external_source(
            "youtube", f"https://youtu.be/{VID}", created_by=default_actor()
        )
        assert child.parent_id == youtube_root.id
        assert child.identifier == VID
        link = CitationSourceLink.objects.get(citation_source=child)
        assert link.url == f"https://www.youtube.com/watch?v={VID}"

    def test_idempotent_across_url_shapes(self, youtube_root):
        first = get_or_create_external_source(
            "youtube", f"https://youtu.be/{VID}", created_by=default_actor()
        )
        second = get_or_create_external_source(
            "youtube",
            f"https://www.youtube.com/watch?v={VID}&t=10s",
            created_by=default_actor(),
        )
        assert first.id == second.id


class TestGetOrCreateWebSourceRootHomepage:
    """Citing a URL equal to a root's own homepage must resolve to a child.

    A root web source is abstract (a container, not citable evidence), so a URL
    that happens to equal its homepage link must create/reuse a child under it —
    never return the root itself.
    """

    HOST = "american-pinball.com"
    HOMEPAGE = "https://american-pinball.com/"

    def _root(self, db) -> CitationSource:
        root = make_citation_source(name="American Pinball", source_type="web")
        make_citation_root_domain(source=root, host=self.HOST)
        make_citation_link(
            citation_source=root,
            link_type="homepage",
            url=self.HOMEPAGE,
        )
        return root

    def test_citing_root_homepage_creates_child_not_root(self, db):
        root = self._root(db)
        source = get_or_create_web_source(self.HOMEPAGE, created_by=default_actor())
        assert source.id != root.id
        assert source.parent_id == root.id

    def test_citing_root_homepage_is_idempotent(self, db):
        self._root(db)
        first = get_or_create_web_source(self.HOMEPAGE, created_by=default_actor())
        second = get_or_create_web_source(self.HOMEPAGE, created_by=default_actor())
        assert first.id == second.id

    def test_rejects_a_malformed_archive_url(self, db):
        # The archive snapshot rides as a second link; it must pass URLField
        # validation too, not just the live url. Atomic: no child is left behind.
        self._root(db)
        page = "https://american-pinball.com/news/launch"
        with pytest.raises(ValidationError):
            get_or_create_web_source(
                page, archive_url="not a url", created_by=default_actor()
            )
        assert not CitationSource.objects.children().exists()

    def test_malformed_subdomain_host_not_recognized_nor_nested(self, db):
        # A malformed host (empty leading label) yields a valid ancestor suffix
        # (american-pinball.com), but recognition's is_dns_host gate abstains, so
        # the URL resolves to no root and nests nothing under the matched domain.
        root = self._root(db)
        with pytest.raises(CitationSource.DoesNotExist):
            get_or_create_web_source(
                "https://www..american-pinball.com/manual.pdf",
                created_by=default_actor(),
            )
        assert not CitationSource.objects.filter(parent=root).exists()
