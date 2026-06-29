import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.citation.test_factories import make_citation_link, make_citation_source

User = get_user_model()


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def citation_source(db):
    """Minimal CitationSource — name + source_type only."""
    return make_citation_source(
        name="The Encyclopedia of Pinball",
        source_type="book",
    )


@pytest.fixture
def citation_source_full(db):
    """CitationSource with all optional fields populated."""
    return make_citation_source(
        name="The Encyclopedia of Pinball - Edition 1",
        source_type="book",
        author="Richard Bueschel",
        publisher="Silverball Amusements",
        year=1996,
        month=6,
        day=15,
        date_note="",
        isbn="0964359219",
        description="First edition hardcover.",
    )


@pytest.fixture
def citation_source_with_parent(db, citation_source):
    """A child CitationSource with parent set."""
    return make_citation_source(
        name="The Encyclopedia of Pinball - Edition 1",
        source_type="book",
        parent=citation_source,
    )


@pytest.fixture
def citation_source_link(db, citation_source):
    """CitationSourceLink on citation_source."""
    return make_citation_link(
        citation_source=citation_source,
        link_type="homepage",
        url="https://archive.org/details/encyclopedia-of-pinball",
        label="archive.org scan",
    )
