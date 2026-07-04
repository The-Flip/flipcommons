"""TikTok scheme tests: its declared example table plus composite-id bespoke.

TikTok is the composite-identity stress case: the identifier is
``<user>/video/<id>`` because the id alone cannot rebuild a watch URL.
``EXAMPLES`` pins the composite grammar's shapes and the deliberate
non-recognition of opaque short links; the bespoke tests cover the canonical
rebuild, the absent time capabilities, and that the composite flows intact
through child minting and the deep-link fallback. Generic invariants live in
``test_conformance``.
"""

import pytest

from apps.accounts.test_factories import default_actor
from apps.citation.citation_types import SCHEME_SPECS
from apps.citation.deep_links import deep_linked_url
from apps.citation.extractors import get_or_create_scheme_child, recognize_url
from apps.citation.test_factories import make_citation_source

from .example_data import SchemeExamples

USER = "scottdanesi"
POST = "7106594312292453675"
IDENTIFIER = f"{USER}/video/{POST}"

tiktok = SCHEME_SPECS["tiktok"]

EXAMPLES = SchemeExamples(
    valid_urls=(
        f"https://tiktok.com/@{USER}/video/{POST}",  # no www
        f"http://www.tiktok.com/@{USER}/video/{POST}",
        f"https://www.tiktok.com/@{USER}/video/{POST}/",  # trailing slash
        f"https://www.tiktok.com/@{USER}/video/{POST}?is_from_webapp=1&lang=en",
        f"https://www.tiktok.com/@{USER}/video/{POST}#comment",
    ),
    invalid_urls=(
        POST,  # the numeric id alone cannot rebuild a watch URL
        f"{USER}/{POST}",  # missing the /video/ separator
        f"https://www.tiktok.com/{USER}/video/{POST}",  # missing the @
        f"https://www.tiktok.com/@{USER}/photo/{POST}",  # photo post
        f"https://www.tiktok.com/@{USER}",  # profile, not a video
        f"https://www.tiktok.com/@{USER}/video/{POST}/duet",  # extra path
        f"https://www.tiktok.com/@Scott{USER}/video/{POST}",  # uppercase user
        "https://vm.tiktok.com/ZMabc123/",  # opaque short link (redirect)
        "https://vt.tiktok.com/ZSabc123/",  # ditto
        "https://www.tiktok.com/t/ZTabc123/",  # ditto, path form
        f"https://m.tiktok.com/v/{POST}.html",  # legacy shape has no username
        f"https://nottiktok.com/@{USER}/video/{POST}",  # look-alike host
    ),
)


def test_canonical_url_rebuilds_the_watch_page() -> None:
    assert (
        tiktok.canonical_url(IDENTIFIER)
        == f"https://www.tiktok.com/@{USER}/video/{POST}"
    )


def test_no_time_capabilities() -> None:
    # TikTok URLs have no seek parameter — the scheme honestly declares neither
    # capability instead of faking a jump URL.
    assert tiktok.deep_link is None
    assert tiktok.start_seconds_from_url is None


class TestTikTokChildMinting:
    """The composite identifier flows intact through the core DB paths."""

    @pytest.fixture
    def tiktok_root(self, db):
        return make_citation_source(
            name="TikTok", source_type="video", identifier_key="tiktok"
        )

    def test_mints_child_keyed_by_the_composite(self, tiktok_root):
        child = get_or_create_scheme_child(
            tiktok_root,
            f"https://www.tiktok.com/@{USER}/video/{POST}?lang=en",
            created_by=default_actor(),
        )
        assert child.identifier == IDENTIFIER
        assert child.source_type == "video"
        assert child.name == f"TikTok #{IDENTIFIER}"
        assert child.links.get().url == tiktok.canonical_url(IDENTIFIER)

    def test_recognition_resolves_url_and_reuses_child(self, tiktok_root):
        child = get_or_create_scheme_child(
            tiktok_root, IDENTIFIER, created_by=default_actor()
        )
        rec = recognize_url(f"https://tiktok.com/@{USER}/video/{POST}")
        assert rec is not None
        assert rec.child is not None
        assert rec.child.id == child.id
        assert rec.identifier == IDENTIFIER
        assert rec.locator_hint == ""  # no seek param exists to hint from

    def test_deep_link_falls_back_to_the_untouched_url(self, tiktok_root):
        # A cited timestamp on a no-seek platform must render beside the plain
        # canonical link — deep_linked_url returns the url unchanged rather than
        # inventing a jump parameter.
        child = get_or_create_scheme_child(
            tiktok_root, IDENTIFIER, created_by=default_actor()
        )
        url = tiktok.canonical_url(IDENTIFIER)
        assert deep_linked_url(child, "1:35", url) == url
