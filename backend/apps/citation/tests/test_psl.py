"""Tests for the Public Suffix List boundary (``apps.citation.psl``).

DB-free: these exercise the bundled snapshot through pure functions. The
``github.io`` canary and the ``registrable_domain``/``is_public_suffix``
equivalence are deliberately pinned so a snapshot bump that changes either
surfaces here rather than silently in production recognition.
"""

import pytest

from apps.citation.hosts import Host, is_dns_host
from apps.citation.psl import is_public_suffix, registrable_domain


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
