"""The generic scalar resolver must not spill relationship claims into extra_data.

``extra_data`` is the overflow bucket for *scalar* claims whose field has no
column on the model, so the API can still filter by them. Relationship-namespace
claims (``media_attachment``, ``credit``, …) resolve into their own tables
(``EntityMedia``, through-tables) and must never land in ``extra_data``.

The generic ``_resolve_single`` / ``_resolve_bulk`` used for every catalog
entity once leaked relationship claims into ``extra_data``: a
Manufacturer/Person/GameplayFeature that carried a media claim spilled it into
``extra_data`` on any scalar re-resolution. Regression test for that leak.
"""

from __future__ import annotations

import pytest

from apps.catalog.claims import build_media_attachment_claim
from apps.catalog.models import Manufacturer
from apps.catalog.resolve._entities import resolve_all_entities, resolve_entity
from apps.media.models import MediaAsset
from apps.provenance.models import Source
from apps.provenance.test_factories import make_claim

pytestmark = pytest.mark.django_db


@pytest.fixture
def source(db):
    return Source.objects.create(
        name="Bootstrap", slug="bootstrap", source_type="editorial", priority=1
    )


@pytest.fixture
def manufacturer_with_media(db, source, user) -> Manufacturer:
    """A Manufacturer whose only relationship claim is a media attachment."""
    mfr = Manufacturer.objects.create(name="Acme", slug="acme", status="active")
    make_claim(mfr, "name", "Acme", source=source)
    make_claim(mfr, "slug", "acme", source=source)
    make_claim(mfr, "status", "active", source=source)
    asset = MediaAsset.objects.create(
        kind=MediaAsset.Kind.IMAGE,
        status=MediaAsset.Status.READY,
        original_filename="logo.jpg",
        mime_type="image/jpeg",
        byte_size=1,
        width=1,
        height=1,
        uploaded_by=user,
    )
    claim_key, value = build_media_attachment_claim(
        mfr, asset.pk, category="logo", is_primary=True
    )
    make_claim(mfr, "media_attachment", value, source=source, claim_key=claim_key)
    return mfr


def test_single_resolve_excludes_media_attachment(manufacturer_with_media):
    resolve_entity(manufacturer_with_media)
    manufacturer_with_media.refresh_from_db()
    assert "media_attachment" not in manufacturer_with_media.extra_data


def test_bulk_resolve_excludes_media_attachment(manufacturer_with_media):
    resolve_all_entities(Manufacturer, object_ids={manufacturer_with_media.pk})
    manufacturer_with_media.refresh_from_db()
    assert "media_attachment" not in manufacturer_with_media.extra_data
