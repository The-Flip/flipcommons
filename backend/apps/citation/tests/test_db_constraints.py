"""Tests for database-level CHECK constraints on citation models.

Verifies that constraints enforce ranges, cross-field invariants, non-blank
rules, nullable IDs, and self-referential anti-cycles at the DB level —
independent of Python validators.
"""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection

from apps.citation.models import (
    CitationSource,
    CitationSourceLink,
    CitationSourceRootDomain,
)


def _raw_update(model, pk, **fields):
    """Bypass ORM validation with a raw SQL UPDATE."""
    table = model._meta.db_table
    sets = ", ".join(f"{col} = %s" for col in fields)
    with connection.cursor() as cur:
        # Table/column identifiers come from test-controlled ORM metadata; values parameterized.
        sql = f"UPDATE {table} SET {sets} WHERE id = %s"  # noqa: S608
        cur.execute(sql, [*fields.values(), pk])


# ---------------------------------------------------------------------------
# CitationSource: non-blank constraints
# ---------------------------------------------------------------------------


class TestCitationSourceNonBlank:
    def test_empty_name_rejected(self, db):
        with pytest.raises(IntegrityError):
            CitationSource.objects.create(name="", source_type="book")

    def test_empty_source_type_rejected(self, db):
        with pytest.raises(IntegrityError):
            CitationSource.objects.create(name="Test", source_type="")


# ---------------------------------------------------------------------------
# CitationSource: source_type enum
# ---------------------------------------------------------------------------


class TestCitationSourceType:
    def test_invalid_source_type_rejected(self, db):
        with pytest.raises(IntegrityError):
            CitationSource.objects.create(name="Test", source_type="invalid")

    @pytest.mark.parametrize("source_type", ["book", "magazine", "web"])
    def test_valid_source_type_accepted(self, db, source_type):
        cs = CitationSource.objects.create(name="Test", source_type=source_type)
        assert cs.pk is not None


# ---------------------------------------------------------------------------
# CitationSource: identifier_key enum
# ---------------------------------------------------------------------------


class TestCitationSourceIdentifierKey:
    def test_invalid_identifier_key_rejected(self, db):
        with pytest.raises(IntegrityError):
            CitationSource.objects.create(
                name="Test", source_type="web", identifier_key="bogus"
            )

    def test_empty_identifier_key_accepted(self, db):
        cs = CitationSource.objects.create(name="Test", source_type="web")
        assert cs.identifier_key == ""

    @pytest.mark.parametrize("key", ["ipdb", "opdb", "youtube"])
    def test_valid_identifier_key_accepted(self, db, key):
        cs = CitationSource.objects.create(
            name="Test", source_type="web", identifier_key=key
        )
        assert cs.identifier_key == key


# ---------------------------------------------------------------------------
# CitationSource: self-reference
# ---------------------------------------------------------------------------


class TestCitationSourceParent:
    def test_parent_self_reference_rejected(self, citation_source):
        with pytest.raises(IntegrityError):
            _raw_update(
                CitationSource, citation_source.pk, parent_id=citation_source.pk
            )

    def test_valid_parent_accepted(self, citation_source):
        child = CitationSource.objects.create(
            name="Child", source_type="book", parent=citation_source
        )
        assert child.parent_id == citation_source.pk

    def test_null_parent_accepted(self, db):
        cs = CitationSource.objects.create(name="Root", source_type="book")
        assert cs.parent_id is None


# ---------------------------------------------------------------------------
# CitationSource: year/month/day ranges
# ---------------------------------------------------------------------------


class TestCitationSourceDateRanges:
    @pytest.fixture
    def source(self, db):
        return CitationSource.objects.create(
            name="Test", source_type="book", year=1992, month=6, day=15
        )

    def test_year_above_max_rejected(self, source):
        with pytest.raises(IntegrityError):
            _raw_update(CitationSource, source.pk, year=2101)

    def test_year_below_min_rejected(self, source):
        with pytest.raises(IntegrityError):
            _raw_update(CitationSource, source.pk, year=1799)

    def test_year_at_min_accepted(self, source):
        _raw_update(CitationSource, source.pk, year=1800)
        source.refresh_from_db()
        assert source.year == 1800

    def test_year_at_max_accepted(self, source):
        _raw_update(CitationSource, source.pk, year=2100)
        source.refresh_from_db()
        assert source.year == 2100

    def test_month_zero_rejected(self, source):
        with pytest.raises(IntegrityError):
            _raw_update(CitationSource, source.pk, month=0)

    def test_month_thirteen_rejected(self, source):
        with pytest.raises(IntegrityError):
            _raw_update(CitationSource, source.pk, month=13)

    def test_day_zero_rejected(self, source):
        with pytest.raises(IntegrityError):
            _raw_update(CitationSource, source.pk, day=0)

    def test_day_thirty_two_rejected(self, source):
        with pytest.raises(IntegrityError):
            _raw_update(CitationSource, source.pk, day=32)


# ---------------------------------------------------------------------------
# CitationSource: date component chains
# ---------------------------------------------------------------------------


class TestCitationSourceDateChains:
    def test_month_without_year_rejected(self, db):
        with pytest.raises(IntegrityError):
            CitationSource.objects.create(
                name="Test", source_type="book", month=6, year=None
            )

    def test_day_without_month_rejected(self, db):
        with pytest.raises(IntegrityError):
            CitationSource.objects.create(
                name="Test", source_type="book", year=1992, day=15, month=None
            )

    def test_year_only_accepted(self, db):
        cs = CitationSource.objects.create(name="Test", source_type="book", year=1992)
        assert cs.month is None
        assert cs.day is None

    def test_year_month_accepted(self, db):
        cs = CitationSource.objects.create(
            name="Test", source_type="book", year=1992, month=6
        )
        assert cs.day is None

    def test_year_month_day_accepted(self, db):
        cs = CitationSource.objects.create(
            name="Test", source_type="book", year=1992, month=6, day=15
        )
        assert cs.pk is not None


# ---------------------------------------------------------------------------
# CitationSource: ISBN (nullable unique)
# ---------------------------------------------------------------------------


class TestCitationSourceISBN:
    def test_empty_isbn_rejected(self, db):
        cs = CitationSource.objects.create(
            name="Test", source_type="book", isbn="1234567890"
        )
        with pytest.raises(IntegrityError):
            _raw_update(CitationSource, cs.pk, isbn="")

    def test_null_isbn_accepted(self, db):
        cs = CitationSource.objects.create(name="Test", source_type="book")
        assert cs.isbn is None

    def test_duplicate_isbn_rejected(self, db):
        CitationSource.objects.create(
            name="Book A", source_type="book", isbn="1234567890"
        )
        with pytest.raises(IntegrityError):
            CitationSource.objects.create(
                name="Book B", source_type="book", isbn="1234567890"
            )


# ---------------------------------------------------------------------------
# CitationSourceLink constraints
# ---------------------------------------------------------------------------


class TestCitationSourceLinkConstraints:
    def test_valid_link(self, citation_source):
        link = CitationSourceLink.objects.create(
            citation_source=citation_source,
            link_type="homepage",
            url="https://example.com",
        )
        assert link.pk is not None

    def test_valid_link_with_label(self, citation_source):
        link = CitationSourceLink.objects.create(
            citation_source=citation_source,
            link_type="homepage",
            url="https://example.com",
            label="Example",
        )
        assert link.label == "Example"

    def test_empty_url_rejected(self, citation_source):
        with pytest.raises(IntegrityError):
            CitationSourceLink.objects.create(
                citation_source=citation_source,
                link_type="homepage",
                url="",
            )

    def test_duplicate_url_same_source_rejected(self, citation_source):
        CitationSourceLink.objects.create(
            citation_source=citation_source,
            link_type="homepage",
            url="https://example.com",
        )
        with pytest.raises(IntegrityError):
            CitationSourceLink.objects.create(
                citation_source=citation_source,
                link_type="homepage",
                url="https://example.com",
            )

    def test_duplicate_url_different_source_accepted(self, citation_source):
        CitationSourceLink.objects.create(
            citation_source=citation_source,
            link_type="homepage",
            url="https://example.com",
        )
        other = CitationSource.objects.create(name="Other", source_type="web")
        link = CitationSourceLink.objects.create(
            citation_source=other,
            link_type="homepage",
            url="https://example.com",
        )
        assert link.pk is not None

    @pytest.mark.parametrize(
        "link_type", ["homepage", "catalog", "publisher", "reference", "archive"]
    )
    def test_valid_link_types_accepted(self, citation_source, link_type):
        link = CitationSourceLink.objects.create(
            citation_source=citation_source,
            link_type=link_type,
            url=f"https://example.com/{link_type}",
        )
        assert link.pk is not None

    def test_invalid_link_type_rejected(self, citation_source):
        with pytest.raises(IntegrityError):
            CitationSourceLink.objects.create(
                citation_source=citation_source,
                link_type="bogus",
                url="https://example.com",
            )

    def test_empty_link_type_rejected(self, citation_source):
        with pytest.raises(IntegrityError):
            CitationSourceLink.objects.create(
                citation_source=citation_source,
                link_type="",
                url="https://example.com",
            )


# ---------------------------------------------------------------------------
# CitationSource: identifier constraints
# ---------------------------------------------------------------------------


class TestIdentifierConstraints:
    """Tests for identifier/identifier_key CHECK and UNIQUE constraints."""

    def test_identifier_requires_parent(self, db):
        """Root sources cannot have a non-empty identifier."""
        with pytest.raises(IntegrityError):
            CitationSource.objects.create(
                name="Orphan", source_type="web", identifier="4443"
            )

    def test_identifier_on_child_accepted(self, db):
        """Child sources can have an identifier."""
        parent = CitationSource.objects.create(
            name="IPDB", source_type="web", identifier_key="ipdb"
        )
        child = CitationSource.objects.create(
            name="IPDB #4443", source_type="web", parent=parent, identifier="4443"
        )
        assert child.pk is not None

    def test_identifier_key_requires_root(self, db):
        """Child sources cannot have identifier_key."""
        parent = CitationSource.objects.create(
            name="IPDB", source_type="web", identifier_key="ipdb"
        )
        with pytest.raises(IntegrityError):
            CitationSource.objects.create(
                name="Bad Child",
                source_type="web",
                parent=parent,
                identifier_key="opdb",
            )

    def test_identifier_key_requires_web(self, db):
        """Non-web sources cannot have identifier_key."""
        with pytest.raises(IntegrityError):
            CitationSource.objects.create(
                name="Bad Book", source_type="book", identifier_key="ipdb"
            )

    def test_identifier_key_and_identifier_mutually_exclusive(self, db):
        """A source cannot be both a scheme-holder and value-holder."""
        parent = CitationSource.objects.create(
            name="IPDB", source_type="web", identifier_key="ipdb"
        )
        # Try via raw SQL to bypass ORM checks
        with pytest.raises(IntegrityError):
            _raw_update(
                CitationSource,
                parent.pk,
                identifier_key="ipdb",
                identifier="4443",
            )

    def test_unique_child_identifier(self, db):
        """Two children of the same parent cannot share an identifier."""
        parent = CitationSource.objects.create(
            name="IPDB", source_type="web", identifier_key="ipdb"
        )
        CitationSource.objects.create(
            name="IPDB #4443", source_type="web", parent=parent, identifier="4443"
        )
        with pytest.raises(IntegrityError):
            CitationSource.objects.create(
                name="IPDB #4443 dup",
                source_type="web",
                parent=parent,
                identifier="4443",
            )

    def test_same_identifier_different_parents_accepted(self, db):
        """Different parents can have children with the same identifier."""
        ipdb = CitationSource.objects.create(
            name="IPDB", source_type="web", identifier_key="ipdb"
        )
        opdb = CitationSource.objects.create(
            name="OPDB", source_type="web", identifier_key="opdb"
        )
        c1 = CitationSource.objects.create(
            name="IPDB #100", source_type="web", parent=ipdb, identifier="100"
        )
        c2 = CitationSource.objects.create(
            name="OPDB #100", source_type="web", parent=opdb, identifier="100"
        )
        assert c1.pk is not None
        assert c2.pk is not None

    def test_empty_identifier_not_unique_constrained(self, db):
        """Multiple children with empty identifier are allowed (no constraint fires)."""
        parent = CitationSource.objects.create(name="Jersey Jack", source_type="web")
        c1 = CitationSource.objects.create(
            name="Page 1", source_type="web", parent=parent
        )
        c2 = CitationSource.objects.create(
            name="Page 2", source_type="web", parent=parent
        )
        assert c1.pk is not None
        assert c2.pk is not None


# ---------------------------------------------------------------------------
# CitationSourceRootDomain: recognition-host constraints + root-only rule
# ---------------------------------------------------------------------------


class TestCitationSourceRootDomain:
    """Host uniqueness/shape (DB) and the root-only rule (``clean()``)."""

    def test_valid_domain_on_root(self, db):
        root = CitationSource.objects.create(name="American Pinball", source_type="web")
        rd = CitationSourceRootDomain.objects.create(
            source=root, host="american-pinball.com"
        )
        assert rd.pk is not None

    def test_domain_on_non_web_root_accepted(self, db):
        """Any-root, not web-only: a book/magazine root may own a host too."""
        root = CitationSource.objects.create(name="A Pinball Book", source_type="book")
        rd = CitationSourceRootDomain(source=root, host="pinball-book.example")
        rd.full_clean()  # no source_type restriction
        rd.save()
        assert rd.pk is not None

    def test_empty_host_rejected(self, db):
        root = CitationSource.objects.create(name="Root", source_type="web")
        with pytest.raises(IntegrityError):
            CitationSourceRootDomain.objects.create(source=root, host="")

    def test_duplicate_host_rejected(self, db):
        a = CitationSource.objects.create(name="A", source_type="web")
        b = CitationSource.objects.create(name="B", source_type="web")
        CitationSourceRootDomain.objects.create(source=a, host="example.com")
        with pytest.raises(IntegrityError):
            CitationSourceRootDomain.objects.create(source=b, host="example.com")

    def test_uppercase_host_rejected_at_db(self, db):
        """The lowercase CHECK fires even when ``clean()`` is bypassed."""
        root = CitationSource.objects.create(name="Root", source_type="web")
        with pytest.raises(IntegrityError):
            CitationSourceRootDomain.objects.create(source=root, host="Example.com")

    def test_clean_rejects_domain_on_child(self, db):
        parent = CitationSource.objects.create(name="Root", source_type="web")
        child = CitationSource.objects.create(
            name="Child", source_type="web", parent=parent
        )
        rd = CitationSourceRootDomain(source=child, host="example.com")
        with pytest.raises(ValidationError):
            rd.full_clean()

    def test_clean_accepts_domain_on_root(self, db):
        root = CitationSource.objects.create(name="Root", source_type="web")
        rd = CitationSourceRootDomain(source=root, host="example.com")
        rd.full_clean()  # must not raise

    def test_clean_rejects_public_suffix_host(self, db):
        """A bare public suffix must never be stored: under longest-suffix
        matching it would over-match every unrelated site beneath it."""
        root = CitationSource.objects.create(name="Root", source_type="web")
        for host in ("gov.uk", "co.uk"):
            rd = CitationSourceRootDomain(source=root, host=host)
            with pytest.raises(ValidationError):
                rd.full_clean()

    def test_clean_rejects_non_dns_host(self, db):
        """An IP literal is not a syntactic DNS recognition host."""
        root = CitationSource.objects.create(name="Root", source_type="web")
        rd = CitationSourceRootDomain(source=root, host="127.0.0.1")
        with pytest.raises(ValidationError):
            rd.full_clean()

    def test_clean_accepts_subdomain_and_registrable(self, db):
        """A curator may declare a subdomain verbatim; a registrable domain is
        the ordinary case. Neither is a public suffix."""
        root = CitationSource.objects.create(name="Root", source_type="web")
        for host in ("twip.kineticist.com", "american-pinball.com"):
            rd = CitationSourceRootDomain(source=root, host=host)
            rd.full_clean()  # must not raise

    def test_clean_github_io_canary(self, db):
        """PRIVATE-section boundary at the model edge: ``github.io`` is itself a
        public suffix (rejected), ``foo.github.io`` is one whole site (accepted)."""
        root = CitationSource.objects.create(name="Root", source_type="web")
        with pytest.raises(ValidationError):
            CitationSourceRootDomain(source=root, host="github.io").full_clean()
        # A whole site under the PRIVATE suffix — must not raise.
        CitationSourceRootDomain(source=root, host="foo.github.io").full_clean()

    def test_clean_normalizes_host(self, db):
        """clean() canonicalizes the owned value: lower, www-strip, trailing dot."""
        root = CitationSource.objects.create(name="Root", source_type="web")
        rd = CitationSourceRootDomain(source=root, host="  WWW.Example.com.  ")
        rd.full_clean()
        assert rd.host == "example.com"

    def test_clean_normalizes_lowercase_www_host(self, db):
        """An admin typing a lowercase-but-www host still routes recognition.

        ``www.example.com`` passes both CHECKs and the unique untouched, so
        without normalization it would be a dead recognition row (recognition
        looks up ``example.com``). clean() strips it to the matchable host.
        """
        root = CitationSource.objects.create(name="Root", source_type="web")
        rd = CitationSourceRootDomain(source=root, host="www.example.com")
        rd.full_clean()
        rd.save()
        assert rd.host == "example.com"

    def test_cascade_delete_with_root(self, db):
        root = CitationSource.objects.create(name="Root", source_type="web")
        CitationSourceRootDomain.objects.create(source=root, host="example.com")
        root.delete()
        assert not CitationSourceRootDomain.objects.filter(host="example.com").exists()
