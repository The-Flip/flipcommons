"""Tests for the pure host helpers (``apps.citation.hosts``).

Model-free and DB-free: ``normalize_host`` / ``label_suffixes`` are string
ops and ``longest_suffix_match`` resolves against an in-memory sequence, so
none of these tests touch the database.
"""

import pytest

from apps.citation.hosts import (
    Host,
    PathPrefix,
    RootDomainMatch,
    is_dns_host,
    is_path_prefix,
    is_reserved_tld,
    is_traversal_free_path,
    label_suffixes,
    longest_suffix_match,
    normalize_host,
    normalize_path_prefix,
    path_prefix_matches,
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
        assert longest_suffix_match(url_host, "", DOMAINS) == expected

    def test_no_domains_is_none(self):
        assert longest_suffix_match(Host("american-pinball.com"), "", []) is None

    @pytest.mark.parametrize("order", [[KINETICIST, TWIP], [TWIP, KINETICIST]])
    def test_most_specific_wins_regardless_of_order(self, order):
        # Whether the broader or the more-specific row is seen first, the
        # longest label-boundary suffix always wins.
        assert longest_suffix_match(Host("blog.twip.kineticist.com"), "", order) == TWIP

    def test_expects_a_normalized_host(self):
        # The matcher compares verbatim and does not normalize. The `Host` type
        # guards this precondition at real call sites; here we deliberately
        # fabricate a `Host` from a raw, www-prefixed, mixed-case string (the
        # bypass a raw-SQL row or a careless cast would represent) to prove the
        # matcher coerces nothing internally — it silently misses.
        raw = "WWW.American-Pinball.com"
        assert longest_suffix_match(Host(raw), "", DOMAINS) is None
        assert longest_suffix_match(normalize_host(raw), "", DOMAINS) == AMERICAN


class TestNormalizePathPrefix:
    """``normalize_path_prefix`` canonicalizes slash framing, nothing else."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("", ""),
            ("   ", ""),
            ("/", ""),
            ("///", ""),
            ("/blobby/go/x", "/blobby/go/x"),
            ("blobby/go/x", "/blobby/go/x"),
            ("/blobby/go/x/", "/blobby/go/x"),
            ("  /blobby/go/x/  ", "/blobby/go/x"),
            # Verbatim beyond the framing: case and percent-encoding untouched.
            ("/Blobby/GO/4bd4%20x", "/Blobby/GO/4bd4%20x"),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_path_prefix(raw) == expected

    @pytest.mark.parametrize("raw", ["", "/blobby/go/x", "blobby/go/x/", "/A/B"])
    def test_idempotent(self, raw):
        once = normalize_path_prefix(raw)
        assert normalize_path_prefix(once) == once


class TestIsPathPrefix:
    """``is_path_prefix`` accepts ``""`` and well-formed ``/``-led prefixes."""

    @pytest.mark.parametrize(
        "prefix",
        [
            "",
            "/downloads",
            "/blobby/go/4bd466e8-edb0-49f6-afcc-31250ba5b0f3",
            "/Case/Sensitive",
            "/percent%20encoded",
        ],
    )
    def test_accepts(self, prefix):
        assert is_path_prefix(PathPrefix(prefix)) is True

    @pytest.mark.parametrize(
        "prefix",
        [
            "downloads",  # no leading slash
            "/downloads/",  # trailing slash
            "/a//b",  # empty segment
            "/a?x=1",  # querystring
            "/a#frag",  # fragment
            "/a/../b",  # dot-segment traversal
            "/..",
            "/a/%2e%2e/b",  # percent-encoded traversal
            "/a/%2E%2E/b",  # ... any case
            "/a\\b",  # backslash
        ],
    )
    def test_rejects(self, prefix):
        assert is_path_prefix(PathPrefix(prefix)) is False


class TestIsTraversalFreePath:
    """Dot segments (literal or ``%2e``-spelled) and backslashes flag a path."""

    @pytest.mark.parametrize(
        "url_path",
        ["", "/", "/a/b", "/a.b/c", "/a..b", "/%2ea/b", "/a/b.", "/..d/e"],
    )
    def test_clean(self, url_path):
        # Dots inside a segment (``a.b``, ``a..b``, a trailing ``b.``) are
        # ordinary characters — only a whole segment of dots traverses.
        assert is_traversal_free_path(url_path) is True

    @pytest.mark.parametrize(
        "url_path",
        [
            "/a/../b",
            "/a/./b",
            "/../a",
            "/a/..",
            "/a/%2e%2e/b",
            "/a/%2E%2E/b",
            "/a/%2e/b",
            "/a/.%2e/b",
            "/a/%2e./b",
            "/a\\..\\b",
            "\\a",
        ],
    )
    def test_traversal(self, url_path):
        assert is_traversal_free_path(url_path) is False


TENANT = "/blobby/go/4bd466e8-edb0-49f6-afcc-31250ba5b0f3"


class TestPathPrefixMatches:
    """Segment-boundary matching; bare prefix matches everything."""

    @pytest.mark.parametrize(
        "url_path",
        ["", "/", "/anything", "/a/../b"],
    )
    def test_bare_prefix_matches_every_path(self, url_path):
        assert path_prefix_matches(PathPrefix(""), url_path) is True

    @pytest.mark.parametrize(
        ("url_path", "expected"),
        [
            (TENANT, True),  # exact
            (f"{TENANT}/downloads/FT%20release.pdf", True),  # below
            (f"{TENANT}-evil/downloads/x.pdf", False),  # segment boundary
            (f"{TENANT}extra", False),
            ("/blobby/go/other-tenant/downloads/x.pdf", False),
            ("/blobby", False),  # above the prefix
            (TENANT.upper(), False),  # case-sensitive
            (f"{TENANT}/../other/x.pdf", False),  # traversal never matches
            (f"{TENANT}/%2e%2e/other.pdf", False),
            (f"{TENANT}\\..\\other.pdf", False),
        ],
    )
    def test_prefixed(self, url_path, expected):
        assert path_prefix_matches(PathPrefix(TENANT), url_path) is expected


# Path-scoped rows on a shared CDN host, plus a bare look-alike ancestor row
# (illegitimate on a shared host, but the matcher must still order it sanely).
CARDONA = RootDomainMatch(
    source_id=4,
    source_name="Cardona Pinball Designs",
    host=Host("img1.wsimg.com"),
    path_prefix=PathPrefix(TENANT),
)
OTHER_MAKER = RootDomainMatch(
    source_id=5,
    source_name="Other Maker",
    host=Host("img1.wsimg.com"),
    path_prefix=PathPrefix("/blobby/go/ffffffff-0000-0000-0000-000000000000"),
)
DEEPER = RootDomainMatch(
    source_id=6,
    source_name="Cardona Downloads",
    host=Host("img1.wsimg.com"),
    path_prefix=PathPrefix(f"{TENANT}/downloads"),
)
BARE_CDN = RootDomainMatch(
    source_id=7, source_name="Bare CDN row", host=Host("wsimg.com")
)


class TestLongestSuffixMatchWithPaths:
    """Path-scoped rows: host specificity dominates, then longest prefix."""

    def test_prefixed_row_matches_its_tenant(self):
        match = longest_suffix_match(
            Host("img1.wsimg.com"),
            f"{TENANT}/downloads/FT%20release.pdf",
            [CARDONA, OTHER_MAKER],
        )
        assert match == CARDONA

    def test_wrong_tenant_matches_nothing(self):
        match = longest_suffix_match(
            Host("img1.wsimg.com"),
            "/blobby/go/eeeeeeee-1111-2222-3333-444444444444/downloads/x.pdf",
            [CARDONA, OTHER_MAKER],
        )
        assert match is None

    def test_longest_prefix_wins_within_a_host(self):
        match = longest_suffix_match(
            Host("img1.wsimg.com"),
            f"{TENANT}/downloads/x.pdf",
            [CARDONA, DEEPER],
        )
        assert match == DEEPER

    def test_prefixed_row_beats_bare_ancestor_for_urls_under_the_prefix(self):
        # Host length dominates: the leaf-host prefixed row outranks the bare
        # ancestor-host row for URLs it covers.
        match = longest_suffix_match(
            Host("img1.wsimg.com"),
            f"{TENANT}/downloads/x.pdf",
            [BARE_CDN, CARDONA],
        )
        assert match == CARDONA

    def test_bare_row_loses_nothing_outside_the_prefix(self):
        # Outside every prefix, only the bare row is eligible. (Recognition
        # additionally excludes bare rows for shared hosts before matching —
        # that policy lives in extractors, not here.)
        match = longest_suffix_match(
            Host("img1.wsimg.com"),
            "/blobby/go/other/x.pdf",
            [BARE_CDN, CARDONA],
        )
        assert match == BARE_CDN

    def test_traversal_path_never_reaches_a_prefixed_row(self):
        match = longest_suffix_match(
            Host("img1.wsimg.com"),
            f"{TENANT}/../ffffffff-0000-0000-0000-000000000000/x.pdf",
            [CARDONA, OTHER_MAKER],
        )
        assert match is None
