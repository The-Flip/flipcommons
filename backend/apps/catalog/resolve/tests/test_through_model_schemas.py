"""Snapshot: the spec-derived RelationshipSchema for each through-model namespace.

One ``RelationshipSchema`` per explicit through-model namespace is derived from
the ``claim_relationship_spec`` ClassVars (see
``apps.catalog.claims._register_through_model_schemas``). This locks the
derivation against explicit expected values — every ``MemberSpec`` /
``PayloadSpec`` field plus the ``valid_subjects`` union — so a derivation bug
(e.g. a value-key ``name`` taken from the column instead of ``value_key``, a
dropped ``fk_target``, or a member misfiled as payload) fails here rather than
silently changing canonical claim keys or write-time validation.
"""

from __future__ import annotations

import pytest

from apps.catalog.models import (
    CorporateEntity,
    CreditRole,
    GameplayFeature,
    Location,
    MachineModel,
    Person,
    RewardType,
    Series,
    Tag,
    Theme,
    Title,
)
from apps.provenance.models import ClaimControlledModel
from apps.provenance.validation import (
    FkTarget,
    MemberSpec,
    PayloadSpec,
    get_relationship_schema,
)


def _fk(name: str, model: type[ClaimControlledModel]) -> MemberSpec:
    return MemberSpec(
        name=name,
        scalar_type=int,
        identity=name,
        fk_target=FkTarget(model, "pk"),
    )


class _ExpectedSchema:
    """One namespace's expected derivation — members, payload and subjects."""

    def __init__(
        self,
        members: tuple[MemberSpec, ...],
        payload: tuple[PayloadSpec, ...],
        subjects: set[type[ClaimControlledModel]],
    ) -> None:
        self.members = members
        self.payload = payload
        self.subjects = subjects


EXPECTED: dict[str, _ExpectedSchema] = {
    "theme": _ExpectedSchema((_fk("theme", Theme),), (), {MachineModel}),
    "tag": _ExpectedSchema((_fk("tag", Tag),), (), {MachineModel}),
    # name is the value-key "reward_type", not the squished column "rewardtype".
    "reward_type": _ExpectedSchema(
        (_fk("reward_type", RewardType),), (), {MachineModel}
    ),
    "gameplay_feature": _ExpectedSchema(
        (_fk("gameplay_feature", GameplayFeature),),
        (
            PayloadSpec(
                name="count",
                scalar_type=int,
                nullable=True,
                min_value=1,
            ),
        ),
        {MachineModel},
    ),
    "credit": _ExpectedSchema(
        (_fk("person", Person), _fk("role", CreditRole)),
        (),
        {MachineModel, Series},
    ),
    "abbreviation": _ExpectedSchema(
        (
            MemberSpec(
                name="value",
                scalar_type=str,
                identity="value",
                max_length=50,
            ),
        ),
        (),
        {MachineModel, Title},
    ),
    "location": _ExpectedSchema((_fk("location", Location),), (), {CorporateEntity}),
    # The target-XOR namespace: a nullable FK identity part (key always
    # present, value may be null), a *non-identity* literal member ("" =
    # absent; the wording is data on the edge, not the name of it) and two
    # required choices payloads.
    "model_relationship": _ExpectedSchema(
        (
            MemberSpec(
                name="target_machine",
                scalar_type=int,
                nullable=True,
                identity="target_machine",
                fk_target=FkTarget(MachineModel, "pk"),
            ),
            MemberSpec(
                name="target_label",
                scalar_type=str,
                max_length=300,
            ),
        ),
        (
            PayloadSpec(
                name="relationship_type",
                scalar_type=str,
                required=True,
                max_length=20,
                choices=("conversion", "conversion_kit", "copy", "retheme"),
            ),
            PayloadSpec(
                name="license_status",
                scalar_type=str,
                required=True,
                max_length=20,
                choices=("licensed", "unlicensed", "unknown"),
            ),
        ),
        {MachineModel},
    ),
    # Self-referential parent hierarchies: the member is the parent FK keyed
    # "parent"; the subject is the entity itself.
    "theme_parent": _ExpectedSchema((_fk("parent", Theme),), (), {Theme}),
    "gameplay_feature_parent": _ExpectedSchema(
        (_fk("parent", GameplayFeature),),
        (),
        {GameplayFeature},
    ),
}


@pytest.mark.parametrize("namespace", sorted(EXPECTED))
def test_derived_schema_matches_snapshot(namespace: str) -> None:
    expected = EXPECTED[namespace]
    schema = get_relationship_schema(namespace)
    assert schema is not None, f"namespace {namespace!r} not registered"
    assert schema.members == expected.members
    assert schema.payload == expected.payload
    assert set(schema.valid_subjects) == expected.subjects


def test_value_keys_is_members_then_payload() -> None:
    """The flat compatibility view derives from the structural split."""
    for namespace, expected in EXPECTED.items():
        schema = get_relationship_schema(namespace)
        assert schema is not None
        assert schema.value_keys == expected.members + expected.payload, namespace


def test_model_relationship_xor_groups_derived() -> None:
    """The spec's MemberXor carries into the registered schema as value keys."""
    schema = get_relationship_schema("model_relationship")
    assert schema is not None
    assert schema.xor_groups == (("target_machine",), ("target_label",))


def test_only_model_relationship_declares_xor_groups() -> None:
    """No other namespace silently grows an exclusivity rule."""
    for namespace in EXPECTED:
        schema = get_relationship_schema(namespace)
        assert schema is not None
        if namespace != "model_relationship":
            assert schema.xor_groups is None, namespace
