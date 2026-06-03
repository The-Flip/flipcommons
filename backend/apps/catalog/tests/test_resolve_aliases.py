"""Tests for _resolve_aliases() — sweep and display-casing behaviour.

Tests are parametrized across all alias types via ALIAS_TYPES, ensuring
the generic _resolve_aliases() function works for every registered alias type.
"""

import pytest
from django.contrib.contenttypes.models import ContentType

from apps.catalog.claims import build_relationship_claim
from apps.catalog.models import (
    CorporateEntity,
    GameplayFeature,
    Location,
    Manufacturer,
    Person,
    RewardType,
    Theme,
)
from apps.catalog.resolve._relationships import ALIAS_TYPES, _resolve_aliases
from apps.provenance.models import Claim, Source

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_alias_claims(source, parent_obj, claim_field, aliases: list[str]) -> None:
    """Assert alias claims for *parent_obj*, mirroring ingest_pindata._assert_alias_claims.

    Passing an empty list puts the parent in scope with no pending claims,
    which causes the sweep to delete any stale alias rows.
    """
    ct_id = ContentType.objects.get_for_model(parent_obj).pk
    pending = []
    for alias_str in aliases:
        lower = alias_str.lower()
        claim_key, value = build_relationship_claim(
            claim_field, {"alias_value": lower, "alias_display": alias_str}
        )
        pending.append(
            Claim(
                content_type_id=ct_id,
                object_id=parent_obj.pk,
                field_name=claim_field,
                claim_key=claim_key,
                value=value,
            )
        )
    scope = {(ct_id, parent_obj.pk)}
    Claim.objects.bulk_assert_claims(
        source, pending, sweep_field=claim_field, authoritative_scope=scope
    )


def _create_parent(parent_model):
    """Create a minimal parent instance for any registered alias type."""
    if parent_model == Theme:
        return Theme.objects.create(name="Racing", slug="racing")
    if parent_model == Manufacturer:
        return Manufacturer.objects.create(name="Gottlieb", slug="gottlieb")
    if parent_model == Person:
        return Person.objects.create(name="Pat Lawlor", slug="pat-lawlor")
    if parent_model == GameplayFeature:
        return GameplayFeature.objects.create(name="Multiball", slug="multiball")
    if parent_model == RewardType:
        return RewardType.objects.create(
            name="Extra Ball", slug="extra-ball", display_order=1
        )
    if parent_model == CorporateEntity:
        mfr = Manufacturer.objects.create(name="Test Mfr", slug="test-mfr")
        return CorporateEntity.objects.create(
            name="Test Corp", slug="test-corp", manufacturer=mfr
        )
    if parent_model == Location:
        return Location.objects.create(
            location_path="usa", slug="usa", name="USA", location_type="country"
        )
    raise ValueError(f"Unknown parent model: {parent_model}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def source(db):
    return Source.objects.create(
        name="Flipcommons", source_type="editorial", priority=300
    )


# Build pytest parametrize IDs from claim field names.
_ALIAS_IDS = [at.claim_field for at in ALIAS_TYPES]


# ---------------------------------------------------------------------------
# Parametrized tests across all alias types
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAliasSweptAllTypes:
    @pytest.mark.parametrize("at", ALIAS_TYPES, ids=_ALIAS_IDS)
    def test_aliases_created_on_first_run(self, source, at):
        parent = _create_parent(at.parent_model)
        _assert_alias_claims(
            source, parent, at.claim_field, ["Alt Name A", "Alt Name B"]
        )
        _resolve_aliases(at.parent_model)

        values = set(
            at.alias_model._default_manager.filter(**{at.fk_name: parent}).values_list(
                "value", flat=True
            )
        )
        assert values == {"Alt Name A", "Alt Name B"}

    @pytest.mark.parametrize("at", ALIAS_TYPES, ids=_ALIAS_IDS)
    def test_stale_aliases_swept(self, source, at):
        parent = _create_parent(at.parent_model)
        aliases = at.alias_model._default_manager.filter(**{at.fk_name: parent})

        _assert_alias_claims(source, parent, at.claim_field, ["Stale Alias"])
        _resolve_aliases(at.parent_model)
        assert aliases.count() == 1

        _assert_alias_claims(source, parent, at.claim_field, [])
        _resolve_aliases(at.parent_model)
        assert aliases.count() == 0

    @pytest.mark.parametrize("at", ALIAS_TYPES, ids=_ALIAS_IDS)
    def test_display_case_preserved(self, source, at):
        parent = _create_parent(at.parent_model)

        _assert_alias_claims(source, parent, at.claim_field, ["Mixed Case"])
        _resolve_aliases(at.parent_model)
        assert (
            at.alias_model._default_manager.get(**{at.fk_name: parent}).value
            == "Mixed Case"
        )
