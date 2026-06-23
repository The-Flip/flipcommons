"""Tests for the pure host helpers (``apps.citation.hosts``).

Model-free and DB-free: ``normalize_host`` / ``label_suffixes`` are string
ops and ``longest_suffix_match`` resolves against an in-memory sequence, so
none of these tests touch the database.
"""

import pytest

from apps.citation.hosts import (
    Host,
    RootDomainMatch,
    is_dns_host,
    is_reserved_tld,
    label_suffixes,
    longest_suffix_match,
    normalize_host,
)


class TestNormalizeHost:
    """``normalize_host`` lowercases and strips all leading ``www.`` labels."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("american-pinball.com", "american-pinball.com"),
            ("www.american-pinball.com", "american-pinball.com"),
            ("WWW.American-Pinball.COM", "american-pinball.com"),
            ("S4.American-Pinball.com", "s4.american-pinball.com"),
            ("  www.example.com  ", "example.com"),
            # A trailing FQDN dot is dropped (matches the dotless stored row).
            ("american-pinball.com.", "american-pinball.com"),
            ("www.american-pinball.com.", "american-pinball.com"),
            # All consecutive leading ``www.`` labels are stripped so the result
            # can't shadow the bare domain (a single strip would leave
            # ``www.example.com``, a distinct stored host from ``example.com``).
            ("www.www.example.com", "example.com"),
            ("www.www.www.example.com", "example.com"),
            ("WWW.WWW.Example.com", "example.com"),
            # Only whole ``www.`` labels are stripped, not an embedded prefix.
            ("wwworld.example.com", "wwworld.example.com"),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_host(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "example.com",
            "www.example.com",
            "www.www.example.com",
            "WWW.Example.com.",
            "wwworld.example.com",
        ],
    )
    def test_idempotent(self, raw):
        once = normalize_host(raw)
        assert normalize_host(once) == once


class TestLabelSuffixes:
    """``label_suffixes`` yields every label-boundary suffix, longest first."""

    @pytest.mark.parametrize(
        ("host", "expected"),
        [
            (
                "s4.american-pinball.com",
                ["s4.american-pinball.com", "american-pinball.com", "com"],
            ),
            ("american-pinball.com", ["american-pinball.com", "com"]),
            ("com", ["com"]),
            ("", []),
            (
                "a.b.c.example.com",
                [
                    "a.b.c.example.com",
                    "b.c.example.com",
                    "c.example.com",
                    "example.com",
                    "com",
                ],
            ),
        ],
    )
    def test_suffixes(self, host, expected):
        assert label_suffixes(host) == expected


class TestIsDnsHost:
    """``is_dns_host`` accepts syntactic DNS names, rejects IPs and junk."""

    @pytest.mark.parametrize(
        "host",
        [
            "american-pinball.com",
            "s4.american-pinball.com",
            "a.b.c.example.com",
            "gov.uk",  # syntactically a host; the public-suffix guard is separate
            "x.co",  # single-char label is valid
            "xn--80ak6aa92e.com",  # punycode IDN
        ],
    )
    def test_accepts(self, host):
        assert is_dns_host(Host(host)) is True

    @pytest.mark.parametrize(
        "host",
        [
            "127.0.0.1",  # IPv4 literal
            "::1",  # IPv6 literal
            "192.168.0.1",
            "localhost",  # no dot
            "com",  # no dot
            "",  # empty
            "-leading.com",  # leading hyphen
            "trailing-.com",  # trailing hyphen
            "under_score.com",  # underscore not in DNS charset
            "münchen.de",  # raw-unicode IDN (must be punycode)
            "example.123",  # all-numeric TLD
            "a" * 64 + ".com",  # label over 63 chars
            "a." * 127 + "com",  # whole hostname over 253 chars (labels valid)
        ],
    )
    def test_rejects(self, host):
        assert is_dns_host(Host(host)) is False


class TestIsReservedTld:
    """``is_reserved_tld`` flags RFC special-use rightmost labels."""

    @pytest.mark.parametrize(
        "host",
        ["foo.test", "bar.localhost", "invalid", "site.example", "printer.local"],
    )
    def test_reserved(self, host):
        assert is_reserved_tld(Host(host)) is True

    @pytest.mark.parametrize(
        "host",
        ["american-pinball.com", "gov.uk", "twip.kineticist.com", "example.com", ""],
    )
    def test_not_reserved(self, host):
        # ``example.com`` is a normal .com domain — only a bare ``.example`` TLD
        # is reserved, not the second-level label.
        assert is_reserved_tld(Host(host)) is False


# A handful of seeded recognition rows to resolve against.
AMERICAN = RootDomainMatch(
    source_id=1, source_name="American Pinball", host=Host("american-pinball.com")
)
KINETICIST = RootDomainMatch(
    source_id=2, source_name="Kineticist", host=Host("kineticist.com")
)
TWIP = RootDomainMatch(
    source_id=3, source_name="This Week in Pinball", host=Host("twip.kineticist.com")
)

DOMAINS = [AMERICAN, KINETICIST, TWIP]


class TestLongestSuffixMatch:
    """Most-specific (longest label-boundary suffix) wins; ties impossible."""

    @pytest.mark.parametrize(
        ("url_host", "expected"),
        [
            # Subdomain collapses to the registrable root.
            ("s4.american-pinball.com", AMERICAN),
            ("american-pinball.com", AMERICAN),
            # The deliberately-seeded subdomain root wins over its parent domain.
            ("twip.kineticist.com", TWIP),
            ("kineticist.com", KINETICIST),
            # A deeper sub-subdomain falls to the nearest seeded root.
            ("cdn.s4.american-pinball.com", AMERICAN),
            ("blog.twip.kineticist.com", TWIP),
            ("other.kineticist.com", KINETICIST),
            # Look-alike host that merely contains the domain as a prefix label.
            ("evil-american-pinball.com", None),
            # Unrelated host.
            ("example.com", None),
            # Empty host.
            ("", None),
        ],
    )
    def test_match(self, url_host, expected):
        assert longest_suffix_match(url_host, DOMAINS) == expected

    def test_no_domains_is_none(self):
        assert longest_suffix_match(Host("american-pinball.com"), []) is None

    @pytest.mark.parametrize("order", [[KINETICIST, TWIP], [TWIP, KINETICIST]])
    def test_most_specific_wins_regardless_of_order(self, order):
        # Whether the broader or the more-specific row is seen first, the
        # longest label-boundary suffix always wins.
        assert longest_suffix_match(Host("blog.twip.kineticist.com"), order) == TWIP

    def test_expects_a_normalized_host(self):
        # The matcher compares verbatim and does not normalize. The `Host` type
        # guards this precondition at real call sites; here we deliberately
        # fabricate a `Host` from a raw, www-prefixed, mixed-case string (the
        # bypass a raw-SQL row or a careless cast would represent) to prove the
        # matcher coerces nothing internally — it silently misses.
        raw = "WWW.American-Pinball.com"
        assert longest_suffix_match(Host(raw), DOMAINS) is None
        assert longest_suffix_match(normalize_host(raw), DOMAINS) == AMERICAN
