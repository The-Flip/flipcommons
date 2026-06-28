"""``build_through_projection`` reproduces every hand-written builder exactly.

REF3's proof obligation: the one generic spec-driven builder is byte-for-byte
equivalent to the nine hand-written ``_*_projection`` builders it will replace in
REF4. Each case pairs the generic projection (via ``relationships_for`` +
``build_through_projection``) with its hand-written counterpart and asserts: the
data ctor args are identical, the scalar shapes reuse the *same* engine
converter objects, credit's compound key uses the generic tuple codecs, and the
per-claim ``extract`` drops/keeps members identically (with the documented
unreachable divergences on a null ``claim.value``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

import pytest

from apps.catalog.models import CorporateEntity, MachineModel, Series, Title
from apps.catalog.resolve._engine import (
    Delta,
    ThroughRowProjection,
    _compound_columns,
    _compound_key,
    reconcile,
)
from apps.catalog.resolve._relationships import (
    M2M_FIELDS,
    _corporate_entity_location_projection,
    _credit_projection,
    _gameplay_projection,
    _m2m_projection,
    _model_abbreviation_projection,
    _title_abbreviation_projection,
)
from apps.catalog.resolve._through_projection import build_through_projection
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.claims import build_relationship_claim
from apps.provenance.model_bases import (
    ClaimControlledModel,
    ClaimRelationshipBinding,
    relationships_for,
)
from apps.provenance.models import Claim, Source
from apps.provenance.test_factories import make_claim

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Seeded target rows — so valid_pks is populated and credit doesn't skip.
# ---------------------------------------------------------------------------

type Pks = dict[str, int]


@pytest.fixture
def pks(db: None) -> Pks:
    """One row per FK target; returns the pks the valid-claim values reference."""
    from apps.catalog.models import (
        CreditRole,
        GameplayFeature,
        Location,
        Person,
        RewardType,
        Tag,
        Theme,
    )

    return {
        "theme": Theme.objects.create(name="Horror", slug="horror").pk,
        "tag": Tag.objects.create(name="Home Use", slug="home-use").pk,
        "reward_type": RewardType.objects.create(
            name="Extra Ball", slug="extra-ball"
        ).pk,
        "gameplay_feature": GameplayFeature.objects.create(
            name="Multiball", slug="multiball"
        ).pk,
        "person": Person.objects.create(name="Pat Lawlor", slug="pat-lawlor").pk,
        "role": CreditRole.objects.create(
            name="Design", slug="design", display_order=10
        ).pk,
        "location": Location.objects.create(
            location_path="usa", slug="usa", name="USA"
        ).pk,
    }


# ---------------------------------------------------------------------------
# The nine shapes, each paired with its hand-written builder.
# ---------------------------------------------------------------------------

# How a hand-written builder behaves on a null ``claim.value`` — the generic
# always drops; the hand-written ones diverge (all unreachable in production).
type NullBehavior = type[Exception] | None  # exception type, or None = also drops


@dataclass(frozen=True)
class _Case:
    id: str
    subject: type[ClaimControlledModel]
    namespace: str
    hand: Callable[[], ThroughRowProjection[Any, Any] | None]
    valid_value: Callable[[Pks], dict[str, object]]
    null_behavior: NullBehavior
    invalid_value: Callable[[Pks], dict[str, object]] | None = None  # None = no FK
    compound: bool = False


def _fk_value(key: str) -> Callable[[Pks], dict[str, object]]:
    return lambda pks: {key: pks[key], "exists": True}


CASES: list[_Case] = [
    _Case(
        "theme",
        MachineModel,
        "theme",
        lambda: _m2m_projection(M2M_FIELDS["theme"]),
        _fk_value("theme"),
        AttributeError,
        lambda pks: {"theme": 10**9, "exists": True},
    ),
    _Case(
        "tag",
        MachineModel,
        "tag",
        lambda: _m2m_projection(M2M_FIELDS["tag"]),
        _fk_value("tag"),
        AttributeError,
        lambda pks: {"tag": 10**9, "exists": True},
    ),
    _Case(
        "reward_type",
        MachineModel,
        "reward_type",
        lambda: _m2m_projection(M2M_FIELDS["reward_type"]),
        _fk_value("reward_type"),
        AttributeError,
        lambda pks: {"reward_type": 10**9, "exists": True},
    ),
    _Case(
        "gameplay_feature",
        MachineModel,
        "gameplay_feature",
        _gameplay_projection,
        lambda pks: {
            "gameplay_feature": pks["gameplay_feature"],
            "count": 3,
            "exists": True,
        },
        AttributeError,
        lambda pks: {"gameplay_feature": 10**9, "exists": True},
    ),
    _Case(
        "credit_model",
        MachineModel,
        "credit",
        lambda: _credit_projection(MachineModel, "model"),
        lambda pks: {"person": pks["person"], "role": pks["role"], "exists": True},
        AttributeError,
        lambda pks: {"person": 10**9, "role": pks["role"], "exists": True},
        compound=True,
    ),
    _Case(
        "credit_series",
        Series,
        "credit",
        lambda: _credit_projection(Series, "series"),
        lambda pks: {"person": pks["person"], "role": pks["role"], "exists": True},
        AttributeError,
        lambda pks: {"person": 10**9, "role": pks["role"], "exists": True},
        compound=True,
    ),
    _Case(
        "abbreviation_model",
        MachineModel,
        "abbreviation",
        _model_abbreviation_projection,
        lambda pks: {"value": "TS4", "exists": True},
        TypeError,
    ),
    _Case(
        "abbreviation_title",
        Title,
        "abbreviation",
        _title_abbreviation_projection,
        lambda pks: {"value": "MM", "exists": True},
        TypeError,
    ),
    _Case(
        "location",
        CorporateEntity,
        "location",
        _corporate_entity_location_projection,
        _fk_value("location"),
        None,
        lambda pks: {"location": 10**9, "exists": True},
    ),
]
CASE_IDS = [c.id for c in CASES]


def test_cases_cover_every_binding() -> None:
    """The nine cases are *exactly* the bindings the generic builder must cover.

    Guards against a future explicit through-model whose shape the equivalence
    suite would otherwise silently skip. ``relationships_for`` returns only the
    explicit-ClassVar specs (not parents/aliases/media), which is the generic
    builder's whole domain.
    """
    from apps.catalog._walks import catalog_models

    actual = {
        (b.subject_model, b.spec.namespace)
        for model in catalog_models()
        for b in relationships_for(model)
    }
    expected = {(c.subject, c.namespace) for c in CASES}
    assert actual == expected


def _binding(case: _Case) -> ClaimRelationshipBinding:
    matches = [
        b for b in relationships_for(case.subject) if b.spec.namespace == case.namespace
    ]
    assert len(matches) == 1, f"{case.id}: expected one binding, got {len(matches)}"
    return matches[0]


def _generic(case: _Case) -> ThroughRowProjection[Any, Any]:
    projection = build_through_projection(_binding(case))
    assert projection is not None, f"{case.id}: builder unexpectedly skipped"
    return projection


def _claim(value: object) -> Claim:
    """An unsaved claim — ``extract`` only reads ``value`` / ``object_id``."""
    return Claim(object_id=1, value=value)


# ---------------------------------------------------------------------------
# Ctor args + codecs.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_ctor_data_args_match_hand_written(case: _Case, pks: Pks) -> None:
    """The data ctor args + payload codecs are identical to the hand-written builder."""
    g = _generic(case)
    h = case.hand()
    assert h is not None
    assert g.subject_model is h.subject_model
    assert g.field_name == h.field_name
    assert g.through_model is h.through_model
    assert g.subject_column == h.subject_column
    assert g.key_columns == h.key_columns
    assert g.payload_columns == h.payload_columns
    assert g.ignore_conflicts == h.ignore_conflicts
    # Payload codecs are the same engine objects in every shape.
    assert g.columns_to_payload is h.columns_to_payload
    assert g.payload_to_columns is h.payload_to_columns


@pytest.mark.parametrize(
    "case",
    [c for c in CASES if not c.compound],
    ids=[c.id for c in CASES if not c.compound],
)
def test_scalar_key_codecs_reuse_engine_converters(case: _Case, pks: Pks) -> None:
    """Single-member shapes reuse the *same* key converter objects (no new closure)."""
    g = _generic(case)
    h = case.hand()
    assert h is not None
    assert g.columns_to_key is h.columns_to_key
    assert g.key_to_columns is h.key_to_columns


@pytest.mark.parametrize(
    "case", [c for c in CASES if c.compound], ids=[c.id for c in CASES if c.compound]
)
def test_compound_key_uses_generic_tuple_codecs(case: _Case, pks: Pks) -> None:
    """Credit's compound key uses the generic tuple codecs (not CreditAssignment)."""
    g = _generic(case)
    assert g.columns_to_key is _compound_key
    assert g.key_to_columns is _compound_columns
    # Round-trips a (person_id, role_id) pair both directions.
    columns = (pks["person"], pks["role"])
    assert g.key_to_columns(g.columns_to_key(columns)) == columns


# ---------------------------------------------------------------------------
# extract() equivalence + drop behavior.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_extract_matches_on_valid_claim(case: _Case, pks: Pks) -> None:
    """A well-formed claim extracts to the same member + payload."""
    g, h = _generic(case), case.hand()
    assert h is not None
    claim = _claim(case.valid_value(pks))
    result = g.extract(claim)
    assert result is not None
    assert result == h.extract(claim)
    if case.compound:
        # The deliberate type change: a plain tuple, not the CreditAssignment
        # NamedTuple (equal to it, but the member type is now generic).
        assert type(result.key) is tuple


@pytest.mark.parametrize(
    "case",
    [c for c in CASES if c.invalid_value is not None],
    ids=[c.id for c in CASES if c.invalid_value is not None],
)
def test_extract_drops_invalid_fk(case: _Case, pks: Pks) -> None:
    """An out-of-range FK pk drops the member in both builders."""
    assert case.invalid_value is not None
    g, h = _generic(case), case.hand()
    assert h is not None
    claim = _claim(case.invalid_value(pks))
    assert g.extract(claim) is None
    assert h.extract(claim) is None


def test_extract_drops_bool_pk(pks: Pks) -> None:
    """``True`` is not an int pk: the strict ``type(x) is int`` guard drops it.

    ``_m2m_projection`` uses the same strict guard, so theme agrees; the generic
    adopts it uniformly. The other hand-written builders use a bare
    ``x not in valid_pks``, where ``True == 1`` would slip through if pk 1 exists
    — so on location the generic's drop is a (production-unreachable) divergence
    the plan called out. Assert the generic drops it on both shapes; the
    hand-written location result is pk-dependent, so we don't pin it.
    """
    theme = next(c for c in CASES if c.id == "theme")
    g, h = _generic(theme), theme.hand()
    assert h is not None
    claim = _claim({"theme": True, "exists": True})
    assert g.extract(claim) is None
    assert h.extract(claim) is None

    location = next(c for c in CASES if c.id == "location")
    assert (
        _generic(location).extract(_claim({"location": True, "exists": True})) is None
    )


# ---------------------------------------------------------------------------
# End-to-end: the generic projection materializes byte-identical through-rows.
# ---------------------------------------------------------------------------


def _is_noop(delta: Delta[Any, Any, Any]) -> bool:
    return not (delta.create or delta.delete or delta.update)


@pytest.mark.parametrize(
    "case",
    [c for c in CASES if c.subject is MachineModel],
    ids=[c.id for c in CASES if c.subject is MachineModel],
)
def test_end_to_end_reconcile_matches_hand_written(case: _Case, pks: Pks) -> None:
    """The generic projection reconciles to the same rows the hand-written one does.

    Materializes from scratch via the generic builder, proves it is idempotent —
    the read↔extract↔diff round-trip is stable, the one interaction the
    component tests can't reach and where the compound tuple codec matters — then
    proves the hand-written builder sees those rows as already-desired, so the
    two materialize byte-identical through-tables. The MachineModel cases cover
    every shape family: single-FK (theme/tag/reward_type), payload (gameplay),
    compound (credit), literal (abbreviation).
    """
    mm = make_machine_model(name="E2E Model", slug="e2e-model")
    source = Source.objects.create(
        name="IPDB", slug="ipdb", source_type="database", priority=10
    )
    identity = cast(
        "Mapping[str, int | str | None]",
        {k: v for k, v in case.valid_value(pks).items() if k != "exists"},
    )
    claim_key, value = build_relationship_claim(case.namespace, identity)
    make_claim(mm, case.namespace, value, source=source, claim_key=claim_key)

    generic, hand = _generic(case), case.hand()
    assert hand is not None

    created = reconcile(generic, {mm.pk})
    assert created.create  # materialized the new rows
    assert not created.delete
    assert not created.update
    assert _is_noop(reconcile(generic, {mm.pk}))  # generic idempotent
    assert _is_noop(reconcile(hand, {mm.pk}))  # hand-written agrees → identical rows


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_null_value_generic_drops_handwritten_diverges(case: _Case, pks: Pks) -> None:
    """A null ``claim.value`` — the generic drops uniformly; the hand-written ones diverge.

    Only location tolerates it (drops too); every other hand-written builder
    raises (``AttributeError`` from cast-then-``.get``, ``TypeError`` from
    abbreviation's subscript). All unreachable in production — validation +
    tombstone filtering guarantee a dict with the key before ``extract`` — so we
    assert the generic's safe drop and document the old builders' crash.
    """
    g, h = _generic(case), case.hand()
    assert h is not None
    claim = _claim(None)
    assert g.extract(claim) is None
    if case.null_behavior is None:
        assert h.extract(claim) is None  # location only
    else:
        with pytest.raises(case.null_behavior):
            h.extract(claim)


# ---------------------------------------------------------------------------
# SKIP_NAMESPACE (credit role) vs DROP_INVALID (everything else).
# ---------------------------------------------------------------------------


def test_credit_skips_when_role_vocabulary_empty() -> None:
    """Credit's SKIP_NAMESPACE role member: empty CreditRole → build returns None."""
    credit = next(c for c in CASES if c.id == "credit_model")
    assert build_through_projection(_binding(credit)) is None


def test_credit_builds_once_roles_seeded(db: None) -> None:
    """With the role vocabulary seeded, credit builds a projection."""
    from apps.catalog.models import CreditRole

    CreditRole.objects.create(name="Design", slug="design", display_order=10)
    credit = next(c for c in CASES if c.id == "credit_model")
    assert build_through_projection(_binding(credit)) is not None


@pytest.mark.parametrize("case_id", ["theme", "location"])
def test_drop_invalid_builds_even_with_empty_target(case_id: str) -> None:
    """A DROP_INVALID FK member builds even with an empty target (drops-and-deletes)."""
    case = next(c for c in CASES if c.id == case_id)
    assert build_through_projection(_binding(case)) is not None
