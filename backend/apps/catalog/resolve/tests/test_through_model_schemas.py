"""Snapshot: the spec-derived RelationshipSchema for each through-model namespace.

REF4 derives one ``RelationshipSchema`` per explicit through-model namespace from
the ``claim_relationship_spec`` ClassVars (see
``apps.catalog.claims._register_through_model_schemas``). This locks the
derivation against explicit expected values — every ``ValueKeySpec`` field plus
the ``valid_subjects`` union — so a derivation bug (e.g. a value-key ``name``
taken from the column instead of ``value_key``, a dropped ``fk_target``, or a
flipped ``required``) fails here rather than silently changing canonical claim
keys or write-time validation.
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
    ValueKeySpec,
    get_relationship_schema,
)


def _fk(name: str, model: type[ClaimControlledModel]) -> ValueKeySpec:
    return ValueKeySpec(
        name=name,
        scalar_type=int,
        required=True,
        identity=name,
        fk_target=FkTarget(model, "pk"),
    )


# namespace → (expected value_keys, expected valid_subjects)
EXPECTED: dict[
    str, tuple[tuple[ValueKeySpec, ...], set[type[ClaimControlledModel]]]
] = {
    "theme": ((_fk("theme", Theme),), {MachineModel}),
    "tag": ((_fk("tag", Tag),), {MachineModel}),
    # name is the value-key "reward_type", not the squished column "rewardtype".
    "reward_type": ((_fk("reward_type", RewardType),), {MachineModel}),
    "gameplay_feature": (
        (
            _fk("gameplay_feature", GameplayFeature),
            ValueKeySpec(
                name="count",
                scalar_type=int,
                required=False,
                nullable=True,
                min_value=1,
            ),
        ),
        {MachineModel},
    ),
    "credit": (
        (_fk("person", Person), _fk("role", CreditRole)),
        {MachineModel, Series},
    ),
    "abbreviation": (
        (
            ValueKeySpec(
                name="value",
                scalar_type=str,
                required=True,
                identity="value",
                max_length=50,
            ),
        ),
        {MachineModel, Title},
    ),
    "location": ((_fk("location", Location),), {CorporateEntity}),
}


@pytest.mark.parametrize("namespace", sorted(EXPECTED))
def test_derived_schema_matches_snapshot(namespace: str) -> None:
    expected_keys, expected_subjects = EXPECTED[namespace]
    schema = get_relationship_schema(namespace)
    assert schema is not None, f"namespace {namespace!r} not registered"
    assert schema.value_keys == expected_keys
    assert set(schema.valid_subjects) == expected_subjects
