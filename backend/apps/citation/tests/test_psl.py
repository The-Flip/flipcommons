"""Tests for the Public Suffix List boundary (``apps.citation.psl``).

DB-free: these exercise the bundled snapshot through pure functions. The
``github.io`` canary and the ``registrable_domain``/``is_public_suffix``
equivalence are deliberately pinned so a snapshot bump that changes either
surfaces here rather than silently in production recognition.
"""

import pytest

from apps.citation.hosts import Host, is_dns_host
from apps.citation.psl import (
    HostError,
    HostRejection,
    is_public_suffix,
    registrable_domain,
    root_host_from_url,
)


class TestIsPublicSuffix:
    """A bare public suffix is one with no registrable label below it."""

    @pytest.mark.parametrize("host", ["com", "co.uk", "gov.uk", "github.io"])
    def test_public_suffix(self, host):
        assert is_public_suffix(Host(host)) is True

    @pytest.mark.parametrize(
        "host",
        [
            "american-pinball.com",
            "dvla.gov.uk",
            "s4.american-pinball.com",
            "foo.github.io",  # PRIVATE-section: a whole site under github.io
            "",
        ],
    )
    def test_not_public_suffix(self, host):
        assert is_public_suffix(Host(host)) is False


class TestRegistrableDomain:
    """Rounds a host down to its registrable domain (public suffix + 1 label)."""

    @pytest.mark.parametrize(
        ("host", "expected"),
        [
            ("s4.american-pinball.com", "american-pinball.com"),
            ("american-pinball.com", "american-pinball.com"),
            ("cdn.s4.american-pinball.com", "american-pinball.com"),
            ("a.b.co.uk", "b.co.uk"),
            ("dvla.gov.uk", "dvla.gov.uk"),
            # PRIVATE section: github.io is the suffix, so the whole site rounds
            # to itself rather than collapsing to github.io.
            ("foo.github.io", "foo.github.io"),
            ("blog.foo.github.io", "foo.github.io"),
        ],
    )
    def test_rounds(self, host, expected):
        assert registrable_domain(Host(host)) == expected

    @pytest.mark.parametrize("host", ["com", "co.uk", "gov.uk", "github.io"])
    def test_bare_public_suffix_has_no_registrable_domain(self, host):
        assert registrable_domain(Host(host)) is None


def test_github_io_canary():
    """Two-directional PRIVATE-section canary, pinned against a snapshot bump.

    ``github.io`` itself is a public suffix (a user can't own it), while
    ``foo.github.io`` is one whole site (registrable on its own). If a snapshot
    update ever demotes the PRIVATE section, both assertions flip together.
    """
    assert is_public_suffix(Host("github.io")) is True
    assert registrable_domain(Host("github.io")) is None
    assert is_public_suffix(Host("foo.github.io")) is False
    assert registrable_domain(Host("foo.github.io")) == "foo.github.io"


@pytest.mark.parametrize(
    "host",
    [
        "com",
        "co.uk",
        "gov.uk",
        "github.io",
        "american-pinball.com",
        "s4.american-pinball.com",
        "dvla.gov.uk",
        "foo.github.io",
        "a.b.co.uk",
    ],
)
def test_registrable_none_iff_public_suffix(host):
    """``registrable_domain(h) is None ⟺ is_public_suffix(h)`` for non-empty hosts.

    Both ``clean()`` (the guard) and the funnel lean on this equivalence; it is
    cross-checked here against the bundled snapshot so a bump that breaks it
    fails the build. The lone exception is the empty host (no registrable domain
    yet not a public suffix), which ``is_dns_host`` rejects upstream before
    either function is ever called.
    """
    h = Host(host)
    # The empty host is the lone exception (no registrable domain, yet not a
    # public suffix); is_dns_host rejects it upstream, so it must never enter
    # this list. This guard fails loudly if someone adds it.
    assert is_dns_host(h) or is_public_suffix(h)
    assert (registrable_domain(h) is None) == is_public_suffix(h)


class TestRootHostFromUrl:
    """The derive funnel: round an untrusted page URL to a storable root host."""

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            # A fuzzy subdomain paste rounds to the registrable domain, so future
            # cites under any subdomain collapse to one root.
            (
                "https://s4.american-pinball.com/games/gtf/manual.pdf",
                "american-pinball.com",
            ),
            ("http://american-pinball.com/", "american-pinball.com"),
            ("https://www.american-pinball.com/x", "american-pinball.com"),
            ("https://a.b.co.uk/page", "b.co.uk"),
            # PRIVATE section: a per-publisher github.io site stays its own root.
            ("https://foo.github.io/post", "foo.github.io"),
            # Port, path and query are stripped by urlparse.hostname.
            ("https://blog.newsite.org:8443/p?q=1", "newsite.org"),
        ],
    )
    def test_rounds_to_registrable_host(self, url, expected):
        assert root_host_from_url(url) == expected

    @pytest.mark.parametrize(
        ("url", "reason"),
        [
            ("https:///just-a-path", HostRejection.NO_HOST),
            ("https://127.0.0.1/page", HostRejection.NOT_DNS),
            ("https://[::1]/page", HostRejection.NOT_DNS),
            # A malformed URL whose host can't be parsed (unterminated IPv6
            # bracket) — urlparse raises ValueError; the funnel must catch it and
            # surface a typed reason, never leak the raw exception.
            ("https://[::1/page", HostRejection.NOT_DNS),
            ("http://foo.test/page", HostRejection.RESERVED_TLD),
            ("http://bar.localhost/page", HostRejection.RESERVED_TLD),
            ("https://gov.uk/page", HostRejection.PUBLIC_SUFFIX),
            ("https://co.uk/page", HostRejection.PUBLIC_SUFFIX),
            # A bare single-label host (``com``) has no dot, so is_dns_host
            # rejects it as NOT_DNS before rounding ever runs.
            ("https://com/page", HostRejection.NOT_DNS),
            # A shared multi-tenant CDN host is nobody's site to root.
            ("https://img1.wsimg.com/blobby/go/uuid/x.pdf", HostRejection.SHARED_HOST),
            ("https://wsimg.com/", HostRejection.SHARED_HOST),
            ("https://cdn.shopify.com/s/files/1/x.pdf", HostRejection.SHARED_HOST),
            (
                "https://storage.googleapis.com/bucket/x.pdf",
                HostRejection.SHARED_HOST,
            ),
        ],
    )
    def test_unroundable_host_raises_typed_reason(self, url, reason):
        with pytest.raises(HostError) as exc:
            root_host_from_url(url)
        assert exc.value.reason is reason

    def test_reserved_tld_rejected_before_rounding(self):
        # is_reserved_tld must run before registrable_domain — accept_unknown=True
        # would otherwise round ``.example`` to itself instead of rejecting it.
        with pytest.raises(HostError) as exc:
            root_host_from_url("https://blog.newsite.example/p")
        assert exc.value.reason is HostRejection.RESERVED_TLD

    def test_shared_host_rejected_on_the_pasted_host_before_rounding(self):
        # The shared check reads the *pasted* host: an asset-subdomain paste
        # (img1.wsimg.com) must be caught even though rounding would land on
        # wsimg.com — otherwise the funnel would mint the ancestor root every
        # tenant's URLs then suffix-match.
        with pytest.raises(HostError) as exc:
            root_host_from_url("https://img1.wsimg.com/blobby/go/uuid/x.pdf")
        assert exc.value.reason is HostRejection.SHARED_HOST

    def test_shared_parent_of_leaf_declaration_still_rounds(self):
        # cdn.shopify.com is declared as a leaf, so shopify.com itself (a
        # legitimate non-shared site) still roots normally.
        assert root_host_from_url("https://shopify.com/blog/post") == "shopify.com"
