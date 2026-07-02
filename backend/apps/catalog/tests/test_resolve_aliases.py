"""Tests for alias resolution — sweep and display-casing behaviour.

Tests are parametrized across all alias types via the live engine alias
registry, ensuring the generic alias projection works for every registered
alias type. The registry is read at collection time (after django.setup() has
run register_alias_types), not snapshotted at import.
"""

import pytest
from django.contrib.contenttypes.models import ContentType

from apps.catalog.engine.aliases import discover_alias_types
from apps.catalog.models import (
    CorporateEntity,
    GameplayFeature,
    Location,
    Manufacturer,
    Person,
    RewardType,
    Theme,
)
from apps.catalog.resolve import resolve_relationship
from apps.provenance.claims import build_relationship_claim
from apps.provenance.models import Claim
from apps.provenance.test_factories import make_claim, make_ingest_source

_ALIAS_TYPES = discover_alias_types()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_alias_claims(source, parent_obj, claim_field, aliases: list[str]) -> None:
    """Set *source*'s alias claims for *parent_obj* as a full sync.

    Deactivates this source's prior active alias claims for the field on the
    parent (the sweep), then creates the new set. Passing an empty list sweeps
    all of them, so the resolver removes any stale alias rows.
    """
    ct_id = ContentType.objects.get_for_model(parent_obj).pk
    # Sweep: deactivate this source's prior active alias claims for the parent.
    Claim.objects.filter(
        actor=source.actor,
        content_type_id=ct_id,
        object_id=parent_obj.pk,
        field_name=claim_field,
        is_active=True,
    ).update(is_active=False)
    # Create the new alias claims as active (through the write primitive, which
    # supplies the source changeset + actor every claim now requires).
    for alias_str in aliases:
        lower = alias_str.lower()
        claim_key, value = build_relationship_claim(
            claim_field, {"alias_value": lower, "alias_display": alias_str}
        )
        make_claim(
            parent_obj,
            claim_field,
            value,
            ingest_source=source,
            claim_key=claim_key,
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
    return make_ingest_source(name="Flipcommons", source_type="editorial", priority=300)


# Build pytest parametrize IDs from claim field names.
_ALIAS_IDS = [at.claim_field for at in _ALIAS_TYPES]


# ---------------------------------------------------------------------------
# Parametrized tests across all alias types
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAliasSweptAllTypes:
    @pytest.mark.parametrize("at", _ALIAS_TYPES, ids=_ALIAS_IDS)
    def test_aliases_created_on_first_run(self, source, at):
        parent = _create_parent(at.parent_model)
        _assert_alias_claims(
            source, parent, at.claim_field, ["Alt Name A", "Alt Name B"]
        )
        resolve_relationship(at.parent_model, at.claim_field)

        values = set(
            at.alias_model._default_manager.filter(**{at.fk_name: parent}).values_list(
                "value", flat=True
            )
        )
        assert values == {"Alt Name A", "Alt Name B"}

    @pytest.mark.parametrize("at", _ALIAS_TYPES, ids=_ALIAS_IDS)
    def test_stale_aliases_swept(self, source, at):
        parent = _create_parent(at.parent_model)
        aliases = at.alias_model._default_manager.filter(**{at.fk_name: parent})

        _assert_alias_claims(source, parent, at.claim_field, ["Stale Alias"])
        resolve_relationship(at.parent_model, at.claim_field)
        assert aliases.count() == 1

        _assert_alias_claims(source, parent, at.claim_field, [])
        resolve_relationship(at.parent_model, at.claim_field)
        assert aliases.count() == 0

    @pytest.mark.parametrize("at", _ALIAS_TYPES, ids=_ALIAS_IDS)
    def test_display_case_preserved(self, source, at):
        parent = _create_parent(at.parent_model)

        _assert_alias_claims(source, parent, at.claim_field, ["Mixed Case"])
        resolve_relationship(at.parent_model, at.claim_field)
        assert (
            at.alias_model._default_manager.get(**{at.fk_name: parent}).value
            == "Mixed Case"
        )
