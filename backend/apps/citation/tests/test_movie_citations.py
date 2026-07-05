"""Movies as parentless-citable video works — the seed proof.

A movie is a ``video`` source with no ``identifier_key`` and no canonical URL:
reached by search, cited with a timestamp locator (see ``MovieCitations.md``).
These tests drive the real seed path (``ensure_root_source``) and the shared
locator chokepoint (``normalized_locator``) to prove the video citation type
supports movies with no new machinery — the abstractness relaxation is all it
takes.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.citation.locators import normalized_locator
from apps.citation.models import CitationSource
from apps.citation.source_node import SourceNode
from apps.citation.source_upsert import ensure_root_source
from apps.provenance.test_factories import make_ingest_source

pytestmark = pytest.mark.django_db

# A representative slice of the proposed pinball-movie seed: parentless video
# works with a year and no scheme/domain/link (no access URL yet).
MOVIES: list[SourceNode] = [
    {
        "name": "Tommy",
        "source_type": "video",
        "year": 1975,
        "description": 'The Who\'s rock opera; its "Pinball Wizard" is the anthem.',
    },
    {
        "name": "Tilt",
        "source_type": "video",
        "year": 1979,
        "description": "Brooke Shields as a teen pinball hustler.",
    },
    {
        "name": "Special When Lit",
        "source_type": "video",
        "year": 2009,
        "description": "Documentary on pinball's rise, fall and collector revival.",
    },
]


@pytest.fixture
def actor(db):
    """A patch ``Source`` actor — the attributor of seeded ``sources:`` rows."""
    return make_ingest_source(
        name="Flip Museum",
        slug="flip-museum-movies",
        source_type="editorial",
        priority=10_000,
    ).actor


class TestMovieSeed:
    def test_movies_seed_as_citable_parentless_video_works(self, actor):
        for node in MOVIES:
            result = ensure_root_source(node, actor=actor, warnings=[])
            assert result.source_created

        for node in MOVIES:
            movie = CitationSource.objects.get(name=node["name"])
            assert movie.source_type == "video"
            assert movie.year == node["year"]
            # A movie: a schemeless, parentless work — not a platform.
            assert movie.identifier_key == ""
            assert movie.is_root is True
            # Citable directly (the whole point of the relaxation), never a
            # container to steer away from.
            assert movie.is_abstract(has_children=False) is False

    def test_a_movie_mints_no_recognition_domain(self, actor):
        """A movie has no canonical URL, so it is reached by search, never by
        URL recognition — it declares no host and owns no root domain."""
        ensure_root_source(MOVIES[0], actor=actor, warnings=[])
        movie = CitationSource.objects.get(name="Tommy")
        assert movie.root_domains.count() == 0

    def test_reseeding_is_idempotent(self, actor):
        """Re-applying the seed matches the existing row instead of duplicating
        it (the additive get-or-create by ``(name, source_type)``)."""
        first = ensure_root_source(MOVIES[0], actor=actor, warnings=[])
        second = ensure_root_source(MOVIES[0], actor=actor, warnings=[])
        assert first.source_created is True
        assert second.source_created is False
        assert CitationSource.objects.filter(name="Tommy").count() == 1


class TestMovieTimestampLocator:
    """A movie cite carries a timestamp locator — the video type's grammar,
    validated at the shared write-path chokepoint."""

    def test_timestamp_locator_is_canonicalized(self):
        # Every accepted input form normalizes to the canonical human form.
        assert normalized_locator("video", "3723") == "1:02:03"
        assert normalized_locator("video", "1h2m3s") == "1:02:03"
        assert normalized_locator("video", "95") == "1:35"

    def test_a_movie_may_be_cited_whole_no_locator(self):
        # The locator is optional: citing the film as a whole is legitimate.
        assert normalized_locator("video", "") == ""

    def test_a_malformed_timestamp_is_rejected(self):
        with pytest.raises(ValidationError) as exc:
            normalized_locator("video", "the pinball scene")
        assert "locator" in exc.value.message_dict
