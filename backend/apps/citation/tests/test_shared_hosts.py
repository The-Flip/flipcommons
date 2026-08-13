"""Tests for the declared shared-CDN host table (``apps.citation.shared_hosts``).

Model-free and DB-free: the table is pure configuration and the lookup is a
string suffix match, so none of these tests touch the database.
"""

import pytest

from apps.citation.hosts import Host
from apps.citation.shared_hosts import (
    SharedHostSpec,
    _validate_and_index,
    shared_host_for,
)


class TestSharedHostFor:
    """Label-boundary suffix lookup against the declared table."""

    @pytest.mark.parametrize(
        ("host", "label"),
        [
            # The GoDaddy CDN is declared at its registrable domain, so every
            # asset subdomain resolves — and the bare domain itself does too,
            # which is what blocks a bare ancestor registration.
            ("img1.wsimg.com", "GoDaddy Website Builder CDN"),
            ("img2.wsimg.com", "GoDaddy Website Builder CDN"),
            ("nebula.wsimg.com", "GoDaddy Website Builder CDN"),
            ("wsimg.com", "GoDaddy Website Builder CDN"),
            ("cdn.shopify.com", "Shopify CDN"),
            ("assets.cdn.shopify.com", "Shopify CDN"),
            ("storage.googleapis.com", "Google Cloud Storage"),
            # Facebook is declared at its registrable domain: every
            # facebook.com URL is a tenant page, path-addressed.
            ("facebook.com", "Facebook"),
            ("m.facebook.com", "Facebook"),
        ],
    )
    def test_matches(self, host, label):
        spec = shared_host_for(Host(host))
        assert spec is not None
        assert spec.label == label

    @pytest.mark.parametrize(
        "host",
        [
            # Leaf declarations don't taint legitimate parents or siblings.
            "shopify.com",
            "googleapis.com",
            "www.googleapis.com",
            # Label-boundary: a look-alike is not a suffix match.
            "evil-wsimg.com",
            "notcdn.shopify.com.example.com",
            "american-pinball.com",
            "",
        ],
    )
    def test_misses(self, host):
        assert shared_host_for(Host(host)) is None


class TestDeclarationValidation:
    """Malformed declarations fail at import, not at first recognition."""

    def test_unnormalized_host_rejected(self):
        with pytest.raises(ValueError, match="normalized DNS names"):
            _validate_and_index(
                (SharedHostSpec(label="Bad", hosts=("WWW.Example.com",)),)
            )

    def test_non_dns_host_rejected(self):
        with pytest.raises(ValueError, match="normalized DNS names"):
            _validate_and_index((SharedHostSpec(label="Bad", hosts=("127.0.0.1",)),))

    def test_duplicate_host_rejected(self):
        with pytest.raises(ValueError, match="declared twice"):
            _validate_and_index(
                (
                    SharedHostSpec(label="A", hosts=("cdn.example.com",)),
                    SharedHostSpec(label="B", hosts=("cdn.example.com",)),
                )
            )

    def test_nested_hosts_rejected(self):
        with pytest.raises(ValueError, match="nests under"):
            _validate_and_index(
                (SharedHostSpec(label="A", hosts=("example.com", "cdn.example.com")),)
            )
