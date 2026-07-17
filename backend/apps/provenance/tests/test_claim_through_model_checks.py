"""Tests for the ``check_claim_through_models`` system check.

The classifier (``_classify_through_model``) is pure over ``_ThroughModelFacts``,
so each failure mode is exercised with synthetic facts rather than fabricated
Django models. ``test_real_models_pass`` is the acceptance test: the live
through-model graph must classify cleanly, which is what makes the check safe to
register at boot.
"""

from __future__ import annotations

from django.db.models import Q

from apps.provenance.model_bases import (
    ClaimRelationshipSpec,
    EmptyTargetPolicy,
    MemberField,
    MemberXor,
    PayloadField,
    SingleSubject,
    XorSubject,
)
from apps.provenance.model_bases.checks import (
    _classify_through_model,
    _ThroughModelFacts,
    _UniqueShape,
    check_claim_through_models,
)


def _ids(facts: _ThroughModelFacts) -> list[str]:
    return sorted(str(e.id) for e in _classify_through_model(facts))


def _single_facts(
    *,
    spec: ClaimRelationshipSpec | None,
    field_names: frozenset[str] = frozenset({"machinemodel", "theme"}),
    uniques: tuple[_UniqueShape, ...] = (
        _UniqueShape(frozenset({"machinemodel", "theme"}), None),
    ),
) -> _ThroughModelFacts:
    return _ThroughModelFacts(
        label="app.Through",
        spec=spec,
        field_names=field_names,
        uniques=uniques,
    )


def _theme_spec(*, identity: str | None = "theme") -> ClaimRelationshipSpec:
    return ClaimRelationshipSpec(
        namespace="theme",
        subject=SingleSubject("machinemodel"),
        members=(MemberField("theme", identity=identity),),
    )


def _credit_facts(*, uniques: tuple[_UniqueShape, ...]) -> _ThroughModelFacts:
    return _ThroughModelFacts(
        label="app.Credit",
        spec=ClaimRelationshipSpec(
            namespace="credit",
            subject=XorSubject("model", "series"),
            members=(
                MemberField("person", identity="person"),
                MemberField(
                    "role",
                    identity="role",
                    empty_target=EmptyTargetPolicy.SKIP_NAMESPACE,
                ),
            ),
        ),
        field_names=frozenset({"model", "series", "person", "role"}),
        uniques=uniques,
    )


_CREDIT_UNIQUES = (
    _UniqueShape(frozenset({"model", "person", "role"}), Q(model__isnull=False)),
    _UniqueShape(frozenset({"series", "person", "role"}), Q(series__isnull=False)),
)


# --- Happy paths ---------------------------------------------------------


def test_well_formed_single_subject_passes() -> None:
    assert _ids(_single_facts(spec=_theme_spec())) == []


def test_well_formed_xor_subject_passes() -> None:
    assert _ids(_credit_facts(uniques=_CREDIT_UNIQUES)) == []


def test_payload_field_is_not_part_of_identity() -> None:
    """A non-identity payload column (gameplay ``count``) stays out of the UC."""
    spec = ClaimRelationshipSpec(
        namespace="gameplay_feature",
        subject=SingleSubject("machinemodel"),
        members=(
            MemberField(
                "gameplayfeature",
                value_key="gameplay_feature",
                identity="gameplay_feature",
            ),
        ),
        payload=(PayloadField("count", nullable=True),),
    )
    facts = _ThroughModelFacts(
        label="app.Gameplay",
        spec=spec,
        field_names=frozenset({"machinemodel", "gameplayfeature", "count"}),
        uniques=(_UniqueShape(frozenset({"machinemodel", "gameplayfeature"}), None),),
    )
    assert _ids(facts) == []


# --- Failure modes -------------------------------------------------------


def test_missing_spec_reports_e001() -> None:
    assert _ids(_single_facts(spec=None)) == ["provenance.E001"]


def test_bad_member_cardinality_reports_e002() -> None:
    spec = ClaimRelationshipSpec(
        namespace="theme",
        subject=SingleSubject("machinemodel"),
        members=(),
    )
    assert "provenance.E002" in _ids(_single_facts(spec=spec))


def test_unresolvable_field_reports_e003_and_short_circuits() -> None:
    spec = ClaimRelationshipSpec(
        namespace="theme",
        subject=SingleSubject("machinemodel"),
        members=(MemberField("nonexistent", identity="nonexistent"),),
    )
    # Field resolution fails, so the identity/uniqueness checks are skipped.
    assert _ids(_single_facts(spec=spec, uniques=())) == ["provenance.E003"]


def test_identity_label_mismatch_reports_e004() -> None:
    assert _ids(_single_facts(spec=_theme_spec(identity="wrong"))) == [
        "provenance.E004"
    ]


def test_identity_label_matches_value_key_not_field() -> None:
    """``reward_type`` keys on the squished ``rewardtype`` column — identity must
    equal the value key, not the field name."""
    spec = ClaimRelationshipSpec(
        namespace="reward_type",
        subject=SingleSubject("machinemodel"),
        members=(
            MemberField("rewardtype", value_key="reward_type", identity="reward_type"),
        ),
    )
    facts = _single_facts(
        spec=spec,
        field_names=frozenset({"machinemodel", "rewardtype"}),
        uniques=(_UniqueShape(frozenset({"machinemodel", "rewardtype"}), None),),
    )
    assert _ids(facts) == []


def test_single_subject_without_matching_unique_reports_e005() -> None:
    assert _ids(_single_facts(spec=_theme_spec(), uniques=())) == ["provenance.E005"]


def test_single_subject_rejects_conditional_unique() -> None:
    """A SingleSubject identity must be backed by an *unconditional* UC."""
    facts = _single_facts(
        spec=_theme_spec(),
        uniques=(
            _UniqueShape(
                frozenset({"machinemodel", "theme"}), Q(machinemodel__isnull=False)
            ),
        ),
    )
    assert _ids(facts) == ["provenance.E005"]


def test_xor_missing_one_branch_reports_e006_once() -> None:
    facts = _credit_facts(uniques=(_CREDIT_UNIQUES[0],))  # only the model branch
    assert _ids(facts) == ["provenance.E006"]


def test_xor_rejects_wrong_branch_condition() -> None:
    """A conditional UC over the model branch guarded by ``series IS NOT NULL``
    must not satisfy the model branch — the Q condition is matched precisely."""
    facts = _credit_facts(
        uniques=(
            _UniqueShape(
                frozenset({"model", "person", "role"}), Q(series__isnull=False)
            ),
            _CREDIT_UNIQUES[1],
        ),
    )
    assert _ids(facts) == ["provenance.E006"]


def test_xor_rejects_unconditional_unique() -> None:
    """An unconditional UC can't stand in for a per-branch conditional one."""
    facts = _credit_facts(
        uniques=(
            _UniqueShape(frozenset({"model", "person", "role"}), None),
            _CREDIT_UNIQUES[1],
        ),
    )
    assert _ids(facts) == ["provenance.E006"]


# --- member_xor (target-ladder) specs -------------------------------------


def _ladder_spec(
    *,
    member_xor: MemberXor | None = None,
) -> ClaimRelationshipSpec:
    return ClaimRelationshipSpec(
        namespace="model_relationship",
        subject=SingleSubject("machine_model"),
        members=(
            MemberField("target_machine", identity="target_machine", nullable=True),
            MemberField(
                "target_manufacturer", identity="target_manufacturer", nullable=True
            ),
            MemberField("target_label", identity="target_label"),
        ),
        member_xor=member_xor
        or MemberXor(
            groups=(("target_machine",), ("target_manufacturer", "target_label"))
        ),
    )


_LADDER_FIELDS = frozenset(
    {"machine_model", "target_machine", "target_manufacturer", "target_label"}
)
_LADDER_UNIQUES = (
    _UniqueShape(
        frozenset({"machine_model", "target_machine"}),
        Q(target_machine__isnull=False),
    ),
    _UniqueShape(
        frozenset({"machine_model", "target_manufacturer", "target_label"}),
        Q(target_manufacturer__isnull=False),
    ),
    _UniqueShape(
        frozenset({"machine_model", "target_label"}),
        Q(target_machine__isnull=True, target_manufacturer__isnull=True),
    ),
)


def _ladder_facts(
    *,
    spec: ClaimRelationshipSpec | None = None,
    uniques: tuple[_UniqueShape, ...] = _LADDER_UNIQUES,
) -> _ThroughModelFacts:
    return _ThroughModelFacts(
        label="app.ModelRelationship",
        spec=spec or _ladder_spec(),
        field_names=_LADDER_FIELDS,
        uniques=uniques,
    )


def test_well_formed_member_xor_ladder_passes() -> None:
    assert _ids(_ladder_facts()) == []


def test_member_xor_allows_three_members() -> None:
    """E002 widens to 3 members only when member_xor is declared."""
    without_xor = ClaimRelationshipSpec(
        namespace="model_relationship",
        subject=SingleSubject("machine_model"),
        members=_ladder_spec().members,
    )
    assert "provenance.E002" in _ids(
        _ladder_facts(spec=without_xor, uniques=_LADDER_UNIQUES)
    )


def test_member_xor_requires_at_least_two_groups() -> None:
    spec = _ladder_spec(
        member_xor=MemberXor(
            groups=(("target_machine", "target_manufacturer", "target_label"),)
        )
    )
    assert "provenance.E007" in _ids(_ladder_facts(spec=spec))


def test_member_xor_rejects_non_member_field() -> None:
    spec = _ladder_spec(
        member_xor=MemberXor(groups=(("target_machine",), ("nonexistent",)))
    )
    assert "provenance.E007" in _ids(_ladder_facts(spec=spec))


def test_member_xor_rejects_overlapping_groups() -> None:
    spec = _ladder_spec(
        member_xor=MemberXor(
            groups=(("target_machine",), ("target_machine", "target_label"))
        )
    )
    assert "provenance.E007" in _ids(_ladder_facts(spec=spec))


def test_member_xor_uniqueness_requires_full_identity_coverage() -> None:
    """Rung constraints that miss an identity member report E008."""
    assert _ids(_ladder_facts(uniques=_LADDER_UNIQUES[:1])) == ["provenance.E008"]


def test_member_xor_uniqueness_rejects_stray_field() -> None:
    """A rung constraint reaching outside the claim identity reports E008."""
    stray = (
        _UniqueShape(
            frozenset({"machine_model", "target_machine", "license_status"}),
            Q(target_machine__isnull=False),
        ),
    ) + _LADDER_UNIQUES[1:]
    assert _ids(_ladder_facts(uniques=stray)) == ["provenance.E008"]


def test_member_xor_uniqueness_ignores_unconditional_constraints() -> None:
    """An unconditional UC can't stand in for the rung constraints (NULLs
    compare distinct, so it wouldn't dedupe null-bearing identities)."""
    unconditional = (_UniqueShape(frozenset(_LADDER_FIELDS), None),)
    assert _ids(_ladder_facts(uniques=unconditional)) == ["provenance.E008"]


# --- Acceptance ----------------------------------------------------------


def test_real_models_pass() -> None:
    """The live through-model graph classifies cleanly at boot."""
    assert check_claim_through_models(app_configs=None) == []


def test_member_xor_allows_non_identity_member() -> None:
    """A non-identity member may anchor an XOR rung — membership is structural
    (``spec.members``), not inferred from ``identity``, so E007 must not fire.

    This is the narrowed-label shape (ModelRelationships step 7): the label
    leaves the claim key but stays a member, and the rung uniques keyed by the
    remaining identity — ``(machine_model, target_machine)`` where set,
    ``(machine_model)`` alone where null — must satisfy E008 as-is.
    """
    spec = ClaimRelationshipSpec(
        namespace="model_relationship",
        subject=SingleSubject("machine_model"),
        members=(
            MemberField("target_machine", identity="target_machine", nullable=True),
            MemberField("target_label"),
        ),
        member_xor=MemberXor(groups=(("target_machine",), ("target_label",))),
    )
    facts = _ThroughModelFacts(
        label="app.ModelRelationship",
        spec=spec,
        field_names=frozenset({"machine_model", "target_machine", "target_label"}),
        uniques=(
            _UniqueShape(
                frozenset({"machine_model", "target_machine"}),
                Q(target_machine__isnull=False),
            ),
            _UniqueShape(
                frozenset({"machine_model"}),
                Q(target_machine__isnull=True),
            ),
        ),
    )
    assert _ids(facts) == []


def test_member_xor_rejects_payload_field() -> None:
    """A payload field can never anchor an XOR rung — E007, same as unknown."""
    spec = ClaimRelationshipSpec(
        namespace="model_relationship",
        subject=SingleSubject("machine_model"),
        members=(
            MemberField("target_machine", identity="target_machine", nullable=True),
            MemberField("target_label", identity="target_label"),
        ),
        payload=(PayloadField("license_status", required=True),),
        member_xor=MemberXor(groups=(("target_machine",), ("license_status",))),
    )
    facts = _ThroughModelFacts(
        label="app.ModelRelationship",
        spec=spec,
        field_names=frozenset(
            {"machine_model", "target_machine", "target_label", "license_status"}
        ),
        uniques=_LADDER_UNIQUES,
    )
    assert "provenance.E007" in _ids(facts)
