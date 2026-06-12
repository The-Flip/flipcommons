"""Tests for catalog/claims.py and provenance make_claim_key()."""

import pytest

from apps.catalog.claims import (
    AliasIdentity,
    build_relationship_claim,
    get_relationship_namespaces,
    make_authoritative_scope,
    normalize_abbreviation_value,
    normalize_alias_identity,
)
from apps.catalog.models import MachineModel, Manufacturer
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.models import make_claim_key

# ---------------------------------------------------------------------------
# make_claim_key (provenance utility)
# ---------------------------------------------------------------------------


class TestMakeClaimKey:
    def test_scalar_returns_field_name(self):
        assert make_claim_key("name") == "name"

    def test_with_identity_parts(self):
        key = make_claim_key("credit", person=42, role=7)
        assert key == "credit|person:42|role:7"

    def test_identity_parts_sorted(self):
        key = make_claim_key("credit", role=7, person=42)
        assert key == "credit|person:42|role:7"

    def test_none_becomes_null(self):
        key = make_claim_key("recipient", person=42, year=None)
        assert key == "recipient|person:42|year:null"

    def test_pipe_in_value_escaped(self):
        key = make_claim_key("credit", person="bad|value")
        assert key == "credit|person:bad%7Cvalue"

    def test_colon_in_value_escaped(self):
        key = make_claim_key("credit", person="bad:value")
        assert key == "credit|person:bad%3Avalue"

    def test_percent_in_value_escaped(self):
        key = make_claim_key("credit", person="100%")
        assert key == "credit|person:100%25"


# ---------------------------------------------------------------------------
# build_relationship_claim (catalog helper)
# ---------------------------------------------------------------------------


class TestBuildRelationshipClaim:
    def test_credit_claim(self, credit_targets):
        person_pk = credit_targets["persons"]["pat-lawlor"].pk
        role_pk = credit_targets["roles"]["design"].pk
        key, val = build_relationship_claim(
            "credit", {"person": person_pk, "role": role_pk}
        )
        assert key == f"credit|person:{person_pk}|role:{role_pk}"
        assert val == {"person": person_pk, "role": role_pk, "exists": True}

    def test_exists_false(self, credit_targets):
        person_pk = credit_targets["persons"]["pat-lawlor"].pk
        role_pk = credit_targets["roles"]["design"].pk
        _, val = build_relationship_claim(
            "credit", {"person": person_pk, "role": role_pk}, exists=False
        )
        assert val["exists"] is False

    def test_tombstone_strips_non_identity_keys(self):
        # Step 8 invariant: an exists=False claim carries only schema-identity
        # keys + exists — alias_display (non-identity) is dropped, so every
        # write path produces a byte-identical tombstone.
        _, val = build_relationship_claim(
            "manufacturer_alias",
            {"alias_value": "stern inc", "alias_display": "Stern Inc"},
            exists=False,
        )
        assert val == {"alias_value": "stern inc", "exists": False}

    def test_assert_keeps_non_identity_keys(self):
        _, val = build_relationship_claim(
            "manufacturer_alias",
            {"alias_value": "stern inc", "alias_display": "Stern Inc"},
        )
        assert val == {
            "alias_value": "stern inc",
            "alias_display": "Stern Inc",
            "exists": True,
        }

    def test_unknown_namespace_raises(self):
        with pytest.raises(ValueError, match="Unknown relationship namespace"):
            build_relationship_claim("bogus", {"person": 1, "role": 2})

    def test_missing_required_key_raises(self):
        with pytest.raises(ValueError, match="Missing required key"):
            build_relationship_claim("credit", {"person": 1})


class TestCanonicalFold:
    """The string folds shared by the editor and the data-patch adapter."""

    def test_alias_strips_and_lowercases(self):
        assert normalize_alias_identity("  Stern Pinball  ") == AliasIdentity(
            value="stern pinball", display="Stern Pinball"
        )

    def test_alias_value_drives_identity_display_preserves_case(self):
        ident = normalize_alias_identity("MedMad")
        assert ident.value == "medmad"
        assert ident.display == "MedMad"

    def test_abbreviation_strips_only_no_casefold(self):
        assert normalize_abbreviation_value("  MM  ") == "MM"


# ---------------------------------------------------------------------------
# make_authoritative_scope
# ---------------------------------------------------------------------------


class TestMakeAuthoritativeScope:
    def test_builds_scope(self, db):
        m1 = make_machine_model(name="Game 1", slug="game-1")
        m2 = make_machine_model(name="Game 2", slug="game-2")
        scope = make_authoritative_scope(MachineModel, {m1.pk, m2.pk})
        from django.contrib.contenttypes.models import ContentType

        ct_id = ContentType.objects.get_for_model(MachineModel).pk
        assert scope == {(ct_id, m1.pk), (ct_id, m2.pk)}

    def test_empty_ids(self, db):
        scope = make_authoritative_scope(Manufacturer, set())
        assert scope == set()


# ---------------------------------------------------------------------------
# get_relationship_namespaces()
# ---------------------------------------------------------------------------


class TestRelationshipNamespaces:
    def test_contains_credit_and_theme(self):
        ns = get_relationship_namespaces()
        assert "credit" in ns
        assert "theme" in ns


# ---------------------------------------------------------------------------
# Registry invariants
# ---------------------------------------------------------------------------


class TestEagerAliasDiscovery:
    """Alias schemas are registered eagerly during ``CatalogConfig.ready()``.

    Pin the contract that every alias namespace is queryable the moment
    Django finishes startup, without any resolver-path call required to
    trigger discovery.
    """

    def test_theme_alias_registered_without_prior_resolver_access(self):
        from apps.provenance.validation import get_relationship_schema

        assert get_relationship_schema("theme_alias") is not None


class TestMediaAttachmentValidSubjectsPin:
    """``media_attachment.valid_subjects`` is derived from ``apps.get_models()``.

    Pin the expected set so a new ``MediaSupportedModel`` subclass (or the
    removal of an existing one) fails in CI rather than silently drifting.
    Update this test when the set genuinely changes.
    """

    def test_expected_subjects(self):
        from apps.catalog.models import (
            GameplayFeature,
            MachineModel,
            Manufacturer,
            Person,
        )
        from apps.provenance.validation import get_relationship_schema

        schema = get_relationship_schema("media_attachment")
        assert schema is not None
        assert schema.valid_subjects == frozenset(
            {GameplayFeature, MachineModel, Manufacturer, Person}
        )


class TestBuildRelationshipClaimCanonicalKey:
    """``build_relationship_claim`` output agrees with ``make_claim_key``.

    Write-path validation rejects any relationship claim whose ``claim_key``
    doesn't match ``make_claim_key`` composed from the value's identity
    fields. This test pins that every registered schema round-trips cleanly
    through ``build_relationship_claim`` into the canonical key form, so a
    refactor of either composition can't silently start failing validation
    on every production write.
    """

    def test_every_schema_produces_canonical_claim_key(self, db):
        from apps.provenance.models import IdentityPart
        from apps.provenance.validation import get_all_relationship_schemas

        for namespace, schema in get_all_relationship_schemas().items():
            identity_kwargs: dict[str, IdentityPart] = {}
            for spec in schema.value_keys:
                if spec.identity is None:
                    continue
                # No current identity spec uses scalar_type=bool, so int|str
                # covers every case. If that ever changes, extend here.
                if spec.scalar_type is int:
                    identity_kwargs[spec.name] = 1
                elif spec.scalar_type is str:
                    identity_kwargs[spec.name] = "x"
                else:
                    raise AssertionError(
                        f"identity spec {namespace}.{spec.name} has "
                        f"unexpected scalar_type {spec.scalar_type!r}"
                    )

            claim_key, _value = build_relationship_claim(
                namespace, identity_kwargs, exists=True
            )
            expected_parts = {
                spec.identity: identity_kwargs[spec.name]
                for spec in schema.value_keys
                if spec.identity is not None
            }
            assert claim_key == make_claim_key(namespace, **expected_parts), (
                f"build_relationship_claim/make_claim_key drift on {namespace!r}"
            )
