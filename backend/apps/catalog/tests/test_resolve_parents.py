import pytest

from apps.catalog.models import GameplayFeature
from apps.catalog.resolve._relationships import resolve_gameplay_feature_parents
from apps.provenance.claims import build_relationship_claim
from apps.provenance.models import Source
from apps.provenance.test_factories import make_claim


@pytest.fixture
def pindata_source(db):
    return Source.objects.create(
        name="Flipcommons Catalog", source_type="editorial", priority=300
    )


class TestResolveGameplayFeatureParents:
    """Regression: _resolve_parents derived the claim field_name from
    model._meta.model_name ('gameplayfeature') but claims were stored
    under 'gameplay_feature_parent'.  The resolver silently found zero
    claims and materialised nothing."""

    def test_parent_m2m_materialised(self, pindata_source):
        parent = GameplayFeature.objects.create(name="Multiball", slug="multiball")
        child = GameplayFeature.objects.create(
            name="2-Ball Multiball", slug="2-ball-multiball"
        )

        claim_key, value = build_relationship_claim(
            "gameplay_feature_parent", {"parent": parent.pk}
        )
        make_claim(
            child,
            "gameplay_feature_parent",
            value,
            source=pindata_source,
            claim_key=claim_key,
        )

        resolve_gameplay_feature_parents()

        assert list(child.parents.values_list("slug", flat=True)) == ["multiball"]
        assert list(parent.children.values_list("slug", flat=True)) == [
            "2-ball-multiball"
        ]
