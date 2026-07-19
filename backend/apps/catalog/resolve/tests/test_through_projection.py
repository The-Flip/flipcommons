"""``build_through_projection`` snapshot + behavior tests.

The generic spec-driven builder is the sole resolution path for every explicit
through-model namespace. This suite pins what it produces against explicit
expected values (the ctor data args + the engine codec objects per shape) and
exercises the extract-level behavior no higher-level test reaches: invalid/bool
FK drops, null-value drops, and the ``SKIP_NAMESPACE`` vs ``DROP_INVALID``
empty-target policies. ``test_cases_cover_every_binding`` keeps the case table
exhaustive against the live binding set.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

import pytest

from apps.catalog.models import (
    CorporateEntity,
    GameplayFeature,
    MachineModel,
    Series,
    Theme,
    Title,
)
from apps.catalog.resolve._engine import (
    ColumnValues,
    Delta,
    ThroughRowProjection,
    _compound_columns,
    _compound_key,
    _int_from_column,
    _int_or_none_from_column,
    _no_columns,
    _no_payload,
    _one_column,
    _str_from_column,
    _str_or_none_from_column,
    reconcile,
)
from apps.catalog.resolve._through_projection import build_through_projection
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.claims import build_relationship_claim
from apps.provenance.model_bases import (
    ClaimControlledModel,
    ClaimRelationshipBinding,
    relationships_for,
)
from apps.provenance.models import Claim
from apps.provenance.test_factories import make_claim, make_ingest_source

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
        "target_machine": make_machine_model(name="Rock", slug="rock-target").pk,
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
# The twelve shapes, each with its expected ctor data + codecs (snapshot).
# ---------------------------------------------------------------------------

type Codec = Callable[..., Any]


@dataclass(frozen=True)
class _Case:
    id: str
    subject: type[ClaimControlledModel]
    namespace: str
    subject_column: str
    key_columns: tuple[str, ...]
    payload_columns: tuple[str, ...]
    columns_to_key: Codec
    key_to_columns: Codec
    columns_to_payload: Codec
    payload_to_columns: Codec
    valid_value: Callable[[Pks], dict[str, object]]
    valid_member: Callable[[Pks], object]
    valid_payload: object = None
    ignore_conflicts: bool = False
    invalid_value: Callable[[Pks], dict[str, object]] | None = None  # None = no FK
    compound: bool = False


def _fk_value(key: str) -> Callable[[Pks], dict[str, object]]:
    return lambda pks: {key: pks[key], "exists": True}


def _credit_value(pks: Pks) -> dict[str, object]:
    return {"person": pks["person"], "role": pks["role"], "exists": True}


def _parent_value(target_key: str) -> Callable[[Pks], dict[str, object]]:
    """A ``*_parent`` claim value — the member rides the ``parent`` value-key."""
    return lambda pks: {"parent": pks[target_key], "exists": True}


CASES: list[_Case] = [
    _Case(
        "theme",
        MachineModel,
        "theme",
        subject_column="machinemodel_id",
        key_columns=("theme_id",),
        payload_columns=(),
        columns_to_key=_int_from_column,
        key_to_columns=_one_column,
        columns_to_payload=_no_payload,
        payload_to_columns=_no_columns,
        valid_value=_fk_value("theme"),
        valid_member=lambda pks: pks["theme"],
        invalid_value=lambda pks: {"theme": 10**9, "exists": True},
    ),
    _Case(
        "tag",
        MachineModel,
        "tag",
        subject_column="machinemodel_id",
        key_columns=("tag_id",),
        payload_columns=(),
        columns_to_key=_int_from_column,
        key_to_columns=_one_column,
        columns_to_payload=_no_payload,
        payload_to_columns=_no_columns,
        valid_value=_fk_value("tag"),
        valid_member=lambda pks: pks["tag"],
        invalid_value=lambda pks: {"tag": 10**9, "exists": True},
    ),
    _Case(
        "reward_type",
        MachineModel,
        "reward_type",
        subject_column="machinemodel_id",
        key_columns=("rewardtype_id",),
        payload_columns=(),
        columns_to_key=_int_from_column,
        key_to_columns=_one_column,
        columns_to_payload=_no_payload,
        payload_to_columns=_no_columns,
        valid_value=_fk_value("reward_type"),
        valid_member=lambda pks: pks["reward_type"],
        invalid_value=lambda pks: {"reward_type": 10**9, "exists": True},
    ),
    _Case(
        "gameplay_feature",
        MachineModel,
        "gameplay_feature",
        subject_column="machinemodel_id",
        key_columns=("gameplayfeature_id",),
        payload_columns=("count",),
        columns_to_key=_int_from_column,
        key_to_columns=_one_column,
        columns_to_payload=_int_or_none_from_column,
        payload_to_columns=_one_column,
        valid_value=lambda pks: {
            "gameplay_feature": pks["gameplay_feature"],
            "count": 3,
            "exists": True,
        },
        valid_member=lambda pks: pks["gameplay_feature"],
        valid_payload=3,
        invalid_value=lambda pks: {"gameplay_feature": 10**9, "exists": True},
    ),
    _Case(
        "credit_model",
        MachineModel,
        "credit",
        subject_column="model_id",
        key_columns=("person_id", "role_id"),
        payload_columns=(),
        columns_to_key=_compound_key,
        key_to_columns=_compound_columns,
        columns_to_payload=_no_payload,
        payload_to_columns=_no_columns,
        valid_value=_credit_value,
        valid_member=lambda pks: (pks["person"], pks["role"]),
        invalid_value=lambda pks: {
            "person": 10**9,
            "role": pks["role"],
            "exists": True,
        },
        compound=True,
    ),
    _Case(
        "credit_series",
        Series,
        "credit",
        subject_column="series_id",
        key_columns=("person_id", "role_id"),
        payload_columns=(),
        columns_to_key=_compound_key,
        key_to_columns=_compound_columns,
        columns_to_payload=_no_payload,
        payload_to_columns=_no_columns,
        valid_value=_credit_value,
        valid_member=lambda pks: (pks["person"], pks["role"]),
        invalid_value=lambda pks: {
            "person": 10**9,
            "role": pks["role"],
            "exists": True,
        },
        compound=True,
    ),
    _Case(
        "abbreviation_model",
        MachineModel,
        "abbreviation",
        subject_column="machine_model_id",
        key_columns=("value",),
        payload_columns=(),
        columns_to_key=_str_from_column,
        key_to_columns=_one_column,
        columns_to_payload=_no_payload,
        payload_to_columns=_no_columns,
        valid_value=lambda pks: {"value": "TS4", "exists": True},
        valid_member=lambda pks: "TS4",
    ),
    _Case(
        "abbreviation_title",
        Title,
        "abbreviation",
        subject_column="title_id",
        key_columns=("value",),
        payload_columns=(),
        columns_to_key=_str_from_column,
        key_to_columns=_one_column,
        columns_to_payload=_no_payload,
        payload_to_columns=_no_columns,
        valid_value=lambda pks: {"value": "MM", "exists": True},
        valid_member=lambda pks: "MM",
    ),
    _Case(
        "location",
        CorporateEntity,
        "location",
        subject_column="corporate_entity_id",
        key_columns=("location_id",),
        payload_columns=(),
        columns_to_key=_int_from_column,
        key_to_columns=_one_column,
        columns_to_payload=_no_payload,
        payload_to_columns=_no_columns,
        valid_value=_fk_value("location"),
        valid_member=lambda pks: pks["location"],
        invalid_value=lambda pks: {"location": 10**9, "exists": True},
    ),
    # The target XOR — a single *nullable* FK identity slot (the honest
    # ``int | None`` decoder), with the non-identity label member riding the
    # data columns beside the two-string payload on the tuple codecs.
    _Case(
        "model_relationship",
        MachineModel,
        "model_relationship",
        subject_column="machine_model_id",
        key_columns=("target_machine_id",),
        payload_columns=("target_label", "relationship_type", "license_status"),
        columns_to_key=_int_or_none_from_column,
        key_to_columns=_one_column,
        columns_to_payload=_compound_key,
        payload_to_columns=_compound_columns,
        valid_value=lambda pks: {
            "target_machine": pks["target_machine"],
            "target_label": "",
            "relationship_type": "copy",
            "license_status": "unknown",
            "exists": True,
        },
        valid_member=lambda pks: pks["target_machine"],
        valid_payload=("", "copy", "unknown"),
        invalid_value=lambda pks: {
            "target_machine": 10**9,
            "target_label": "",
            "relationship_type": "copy",
            "license_status": "unknown",
            "exists": True,
        },
    ),
    # The optional target ladder — like model_relationship, a single nullable
    # FK identity slot with the non-identity label riding the data column, but
    # no payload: the single data column takes the scalar (not tuple) codecs.
    # The FK member declares COUNTRY_TARGET_FILTER, so valid_pks holds only
    # root locations (the fixture's "usa" qualifies).
    _Case(
        "export_market",
        MachineModel,
        "export_market",
        subject_column="machine_model_id",
        key_columns=("target_market_location_id",),
        payload_columns=("target_market_label",),
        columns_to_key=_int_or_none_from_column,
        key_to_columns=_one_column,
        columns_to_payload=_str_or_none_from_column,
        payload_to_columns=_one_column,
        valid_value=lambda pks: {
            "target_market_location": pks["location"],
            "target_market_label": "",
            "exists": True,
        },
        valid_member=lambda pks: pks["location"],
        valid_payload="",
        invalid_value=lambda pks: {
            "target_market_location": 10**9,
            "target_market_label": "",
            "exists": True,
        },
    ),
    # Self-referential parent hierarchies — SingleSubject("from_<model>") with
    # the parent FK (to_<model>) as the identity member keyed "parent";
    # ignore_conflicts=True per the through-model spec.
    _Case(
        "theme_parent",
        Theme,
        "theme_parent",
        subject_column="from_theme_id",
        key_columns=("to_theme_id",),
        payload_columns=(),
        columns_to_key=_int_from_column,
        key_to_columns=_one_column,
        columns_to_payload=_no_payload,
        payload_to_columns=_no_columns,
        valid_value=_parent_value("theme"),
        valid_member=lambda pks: pks["theme"],
        ignore_conflicts=True,
        invalid_value=lambda pks: {"parent": 10**9, "exists": True},
    ),
    _Case(
        "gameplay_feature_parent",
        GameplayFeature,
        "gameplay_feature_parent",
        subject_column="from_gameplayfeature_id",
        key_columns=("to_gameplayfeature_id",),
        payload_columns=(),
        columns_to_key=_int_from_column,
        key_to_columns=_one_column,
        columns_to_payload=_no_payload,
        payload_to_columns=_no_columns,
        valid_value=_parent_value("gameplay_feature"),
        valid_member=lambda pks: pks["gameplay_feature"],
        ignore_conflicts=True,
        invalid_value=lambda pks: {"parent": 10**9, "exists": True},
    ),
]
CASE_IDS = [c.id for c in CASES]


def test_cases_cover_every_binding() -> None:
    """The cases are *exactly* the bindings the generic builder must cover.

    Guards against a future explicit through-model whose shape this suite would
    otherwise silently skip. ``relationships_for`` returns every explicit-ClassVar
    spec (incl. the self-referential parents) — not aliases or media — which is
    the generic builder's whole domain.
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
# Ctor args + codecs (snapshot).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_ctor_data_args(case: _Case, pks: Pks) -> None:
    """The data ctor args match the expected snapshot for each shape.

    ``subject_model`` / ``through_model`` / ``field_name`` are copied from the
    binding; the columns and conflict flag are the expected literals.
    """
    binding = _binding(case)
    g = _generic(case)
    assert g.subject_model is case.subject
    assert g.subject_model is binding.subject_model
    assert g.through_model is binding.through_model
    assert g.field_name == case.namespace
    assert g.subject_column == case.subject_column
    assert g.key_columns == case.key_columns
    assert g.payload_columns == case.payload_columns
    assert g.ignore_conflicts == case.ignore_conflicts


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_codecs_are_the_expected_engine_objects(case: _Case, pks: Pks) -> None:
    """Each shape selects the expected key/payload codec objects (no new closure)."""
    g = _generic(case)
    assert g.columns_to_key is case.columns_to_key
    assert g.key_to_columns is case.key_to_columns
    assert g.columns_to_payload is case.columns_to_payload
    assert g.payload_to_columns is case.payload_to_columns


@pytest.mark.parametrize(
    "case", [c for c in CASES if c.compound], ids=[c.id for c in CASES if c.compound]
)
def test_compound_key_round_trips(case: _Case, pks: Pks) -> None:
    """Credit's compound key uses the generic tuple codecs and round-trips."""
    g = _generic(case)
    assert g.columns_to_key is _compound_key
    assert g.key_to_columns is _compound_columns
    columns: ColumnValues = (pks["person"], pks["role"])
    assert g.key_to_columns(g.columns_to_key(columns)) == columns


# ---------------------------------------------------------------------------
# extract() behavior.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_extract_on_valid_claim(case: _Case, pks: Pks) -> None:
    """A well-formed claim extracts to the expected member + payload."""
    g = _generic(case)
    result = g.extract(_claim(case.valid_value(pks)))
    assert result is not None
    assert result.key == case.valid_member(pks)
    assert result.payload == case.valid_payload
    if case.compound:
        # Compound keys are plain tuples, not the old CreditAssignment NamedTuple.
        assert type(result.key) is tuple


@pytest.mark.parametrize(
    "case",
    [c for c in CASES if c.invalid_value is not None],
    ids=[c.id for c in CASES if c.invalid_value is not None],
)
def test_extract_drops_invalid_fk(case: _Case, pks: Pks) -> None:
    """An out-of-range FK pk drops the member."""
    assert case.invalid_value is not None
    assert _generic(case).extract(_claim(case.invalid_value(pks))) is None


def test_extract_drops_bool_pk(pks: Pks) -> None:
    """``True`` is not an int pk: the strict ``type(x) is int`` guard drops it."""
    theme = next(c for c in CASES if c.id == "theme")
    assert _generic(theme).extract(_claim({"theme": True, "exists": True})) is None

    location = next(c for c in CASES if c.id == "location")
    assert (
        _generic(location).extract(_claim({"location": True, "exists": True})) is None
    )


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_extract_drops_null_value(case: _Case, pks: Pks) -> None:
    """A null ``claim.value`` drops uniformly (unreachable in production — validation
    and tombstone filtering guarantee a dict with the key before ``extract``)."""
    assert _generic(case).extract(_claim(None)) is None


# ---------------------------------------------------------------------------
# End-to-end: the generic projection materializes through-rows idempotently.
# ---------------------------------------------------------------------------


def _is_noop(delta: Delta[Any, Any, Any]) -> bool:
    return not (delta.create or delta.delete or delta.update)


@pytest.mark.parametrize(
    "case",
    [c for c in CASES if c.subject is MachineModel],
    ids=[c.id for c in CASES if c.subject is MachineModel],
)
def test_end_to_end_reconcile_is_idempotent(case: _Case, pks: Pks) -> None:
    """The generic projection materializes the rows, then sees them as desired.

    Materializes from scratch, then proves the read↔extract↔diff round-trip is
    stable — the one interaction the component tests can't reach and where the
    compound tuple codec matters. The MachineModel cases cover every shape
    family: single-FK (theme/tag/reward_type), payload (gameplay), compound
    (credit), literal (abbreviation).
    """
    mm = make_machine_model(name="E2E Model", slug="e2e-model")
    source = make_ingest_source(
        name="IPDB", slug="ipdb", source_type="database", priority=10
    )
    identity = cast(
        "Mapping[str, int | str | None]",
        {k: v for k, v in case.valid_value(pks).items() if k != "exists"},
    )
    claim_key, value = build_relationship_claim(case.namespace, identity)
    make_claim(mm, case.namespace, value, ingest_source=source, claim_key=claim_key)

    generic = _generic(case)
    created = reconcile(generic, {mm.pk})
    assert created.create  # materialized the new rows
    assert not created.delete
    assert not created.update
    assert _is_noop(reconcile(generic, {mm.pk}))  # idempotent on a second pass


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
