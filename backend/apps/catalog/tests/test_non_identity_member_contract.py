"""Contract tests for a non-identity member — the narrowed model_relationship shape.

The gate before the real spec change (docs/plans/catalog_data_model/
ClaimIdentityNarrowing.md): before ``target_label`` leaves the claim identity,
every consumer must already honor a member that carries claim data without
contributing to the claim key. The narrowed spec is pure data, so these tests
build it here — ``target_label`` as a member with ``identity=None`` — derive
its schema through the real derivation helpers, patch it into the schema
registry per-test and run it against the real ``ModelRelationship`` table.
Each latent "member ⟺ identity" assumption fails here, not in review.

Once the real spec narrows, these tests describe the live shape; they are kept
(not folded into test_resolve_model_relationships) because they pin the
*contract* — key exclusion, tombstone shape, in-place reword — rather than the
namespace's end-to-end behavior.
"""

import logging

import pytest
from django.core.exceptions import ValidationError

from apps.catalog.claims import _schema_shape_for, _xor_groups_for
from apps.catalog.models import MachineModel, ModelRelationship
from apps.catalog.resolve._engine import reconcile
from apps.catalog.resolve._through_projection import build_through_projection
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.claims import build_relationship_claim
from apps.provenance.display import (
    FkRef,
    LabelLookup,
    _build_relationship_display,
)
from apps.provenance.model_bases import (
    ClaimRelationshipBinding,
    ClaimRelationshipSpec,
    MemberField,
    MemberXor,
    PayloadField,
    SingleSubject,
)
from apps.provenance.models import make_claim_key
from apps.provenance.test_factories import make_claim, make_ingest_source
from apps.provenance.validation import (
    RelationshipSchema,
    _relationship_schemas,
    validate_single_relationship_claim,
)

NARROWED_SPEC = ClaimRelationshipSpec(
    namespace="model_relationship",
    subject=SingleSubject("machine_model"),
    members=(
        MemberField("target_machine", identity="target_machine", nullable=True),
        # The contract under test: a member with no identity label.
        MemberField("target_label"),
    ),
    payload=(
        PayloadField("relationship_type", required=True),
        PayloadField("license_status", required=True),
    ),
    member_xor=MemberXor(groups=(("target_machine",), ("target_label",))),
)

LABEL_EDGE_KEY = "model_relationship|target_machine:null"


def _narrowed_binding() -> ClaimRelationshipBinding:
    return ClaimRelationshipBinding(
        spec=NARROWED_SPEC,
        through_model=ModelRelationship,
        subject_model=MachineModel,
        subject_fk="machine_model",
        accessor="relationships",
    )


@pytest.fixture
def narrowed_schema(monkeypatch):
    """Swap the registered model_relationship schema for the narrowed one.

    Derived through the real registration helpers (``_schema_shape_for`` /
    ``_xor_groups_for``) so the contract exercises the derivation too, and
    installed with ``monkeypatch.setitem`` so every reader of the registry —
    claim construction, validation, display, the patch emitter — sees the
    narrowed shape for the test's duration only.
    """
    binding = _narrowed_binding()
    shape = _schema_shape_for(binding)
    schema = RelationshipSchema(
        namespace="model_relationship",
        members=shape.members,
        payload=shape.payload,
        valid_subjects=frozenset({MachineModel}),
        xor_groups=_xor_groups_for(binding),
    )
    monkeypatch.setitem(_relationship_schemas, "model_relationship", schema)
    return schema


def _positive_value(machine=None, label=""):
    return {
        "target_machine": machine,
        "target_label": label,
        "relationship_type": "copy",
        "license_status": "unknown",
    }


# ---------------------------------------------------------------------------
# Claim construction — the key excludes the wording; tombstones are identity-only
# ---------------------------------------------------------------------------


class TestClaimConstruction:
    def test_label_edge_key_excludes_wording(self, narrowed_schema):
        claim_key, value = build_relationship_claim(
            "model_relationship", _positive_value(label="an unknown Gottlieb game")
        )
        assert claim_key == LABEL_EDGE_KEY
        assert value["target_label"] == "an unknown Gottlieb game"

    def test_reword_shares_the_claim_key(self, narrowed_schema):
        """Two wordings, one slot: a reword supersedes instead of forking."""
        key_a, _ = build_relationship_claim(
            "model_relationship", _positive_value(label="an unknown Gottlieb game")
        )
        key_b, _ = build_relationship_claim(
            "model_relationship", _positive_value(label="an unidentified Gottlieb")
        )
        assert key_a == key_b == LABEL_EDGE_KEY

    def test_machine_edge_key_is_target_only(self, narrowed_schema):
        claim_key, _ = build_relationship_claim(
            "model_relationship", _positive_value(machine=42)
        )
        assert claim_key == "model_relationship|target_machine:42"

    def test_tombstone_is_identity_only_regardless_of_selector(self, narrowed_schema):
        """A ``remove:`` authored with a stale wording must not persist it —
        the tombstone carries the identity and ``exists`` alone, so any
        selector wording folds to the same canonical bytes."""
        by_old = build_relationship_claim(
            "model_relationship",
            {"target_machine": None, "target_label": "old wording"},
            exists=False,
        )
        by_new = build_relationship_claim(
            "model_relationship",
            {"target_machine": None, "target_label": "current wording"},
            exists=False,
        )
        assert by_old == by_new
        assert by_old.value == {"target_machine": None, "exists": False}
        assert by_old.claim_key == LABEL_EDGE_KEY


# ---------------------------------------------------------------------------
# Validation — requiredness by role and polarity
# ---------------------------------------------------------------------------


class TestValidation:
    def _validate(self, value, claim_key=None):
        if claim_key is None:
            claim_key = make_claim_key(
                "model_relationship", target_machine=value.get("target_machine")
            )
        validate_single_relationship_claim(
            subject_model=MachineModel,
            field_name="model_relationship",
            claim_key=claim_key,
            value=value,
        )

    def test_label_edge_positive_passes(self, narrowed_schema):
        self._validate({**_positive_value(label="several EM models"), "exists": True})

    def test_positive_missing_label_rejected(self, narrowed_schema):
        """A non-identity member is still required on positive claims."""
        value = {**_positive_value(machine=42), "exists": True}
        del value["target_label"]
        with pytest.raises(ValidationError, match="missing required key"):
            self._validate(value)

    def test_label_tombstone_identity_only_passes(self, narrowed_schema):
        """The null-identity tombstone: no label key, zero XOR groups present."""
        self._validate({"target_machine": None, "exists": False})

    def test_machine_tombstone_identity_only_passes(self, narrowed_schema):
        self._validate({"target_machine": 42, "exists": False})

    def test_incomplete_tombstone_is_clean_validation_error(self, narrowed_schema):
        """A tombstone missing its identity key must fail as a ValidationError,
        never a KeyError out of the XOR check."""
        with pytest.raises(ValidationError, match="missing required key"):
            self._validate({"exists": False}, claim_key=LABEL_EDGE_KEY)

    def test_positive_with_both_targets_rejected(self, narrowed_schema):
        with pytest.raises(ValidationError, match="exactly one"):
            self._validate(
                {**_positive_value(machine=42, label="redundant"), "exists": True}
            )

    def test_positive_with_no_target_rejected(self, narrowed_schema):
        with pytest.raises(ValidationError, match="exactly one"):
            self._validate({**_positive_value(), "exists": True})


# ---------------------------------------------------------------------------
# Display — the wording is a primary part; tombstones render without noise
# ---------------------------------------------------------------------------


class TestDisplay:
    def test_label_edge_renders_wording_as_primary_part(self, narrowed_schema):
        display = _build_relationship_display(
            {**_positive_value(label="several EM models"), "exists": True},
            narrowed_schema,
            LabelLookup(),
        )
        assert [(p.key, p.label, p.state) for p in display.identity] == [
            ("target_label", "several EM models", "resolved")
        ]
        assert [(q.key, q.value) for q in display.qualifiers] == [
            ("relationship_type", "copy"),
            ("license_status", "unknown"),
        ]

    def test_machine_edge_skips_absent_label_slot(self, narrowed_schema):
        labels = LabelLookup()
        labels.add(FkRef(MachineModel, 42), "Rock (Premier 1985)")
        display = _build_relationship_display(
            {**_positive_value(machine=42), "exists": True},
            narrowed_schema,
            labels,
        )
        assert [(p.key, p.label) for p in display.identity] == [
            ("target_machine", "Rock (Premier 1985)")
        ]

    def test_label_tombstone_renders_without_error_logs(self, narrowed_schema, caplog):
        """An identity-only label tombstone has no present member slot — both
        rungs are absent-by-XOR, so display emits no parts and, critically, no
        "missing identity key" error logs. (Edit-history legibility for the
        removed wording is the history renderer's job — it derives the value
        from the prior positive claim; pinned at the API level in stage 3.)
        """
        with caplog.at_level(logging.ERROR, logger="apps.provenance.display"):
            display = _build_relationship_display(
                {"target_machine": None, "exists": False},
                narrowed_schema,
                LabelLookup(),
            )
        assert display.identity == []
        assert display.qualifiers == []
        assert caplog.records == []


# ---------------------------------------------------------------------------
# Patch emit — authoring slots come from members, not identity
# ---------------------------------------------------------------------------


class TestPatchEmit:
    def _rel_spec(self):
        from apps.claim_ingest.patches.emit import _relationship_member_spec
        from apps.claim_ingest.patches.parsing import EditEntry

        entry = EditEntry(
            entity_type="model",
            public_id="punky-willy",
            retract=[],
            remove={},
            fields={},
        )
        return _relationship_member_spec(MachineModel, "model_relationship", entry)

    def test_label_is_an_authorable_literal_slot(self, narrowed_schema):
        rel_spec = self._rel_spec()
        assert [s.value_key for s in rel_spec.literal_slots] == ["target_label"]
        assert [s.value_key for s in rel_spec.fk_slots] == ["target_machine"]
        assert sorted(s.value_key for s in rel_spec.payload_slots) == [
            "license_status",
            "relationship_type",
        ]

    def test_remove_by_stale_wording_folds_to_one_tombstone(self, narrowed_schema):
        """``remove:`` matches by claim_key; the authored wording is a selector,
        not data — any wording yields byte-identical tombstones."""
        from apps.claim_ingest.patches.emit import _member_identity
        from apps.claim_ingest.patches.parsing import EditEntry

        entry = EditEntry(
            entity_type="model",
            public_id="punky-willy",
            retract=[],
            remove={},
            fields={},
        )
        rel_spec = self._rel_spec()
        tombstones = set()
        for wording in ("old wording", "current wording"):
            identity = _member_identity(
                {"target_label": wording}, "model_relationship", rel_spec, entry
            )
            claim_key, value = build_relationship_claim(
                "model_relationship", identity, exists=False
            )
            tombstones.add((claim_key, tuple(sorted(value.items()))))
        assert len(tombstones) == 1
        ((claim_key, _),) = tombstones
        assert claim_key == LABEL_EDGE_KEY


# ---------------------------------------------------------------------------
# Reconcile — keyed by identity; the wording updates in place
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReconcile:
    @pytest.fixture
    def source(self):
        return make_ingest_source(
            name="IPDB", slug="ipdb", source_type="database", priority=10
        )

    @pytest.fixture
    def high_source(self):
        return make_ingest_source(
            name="Editorial", slug="editorial", source_type="editorial", priority=100
        )

    @pytest.fixture
    def subject(self):
        return make_machine_model(name="Punky Willy", slug="punky-willy")

    def _mint(self, subject, source, *, machine=None, label="", exists=True):
        values = {"target_machine": machine, "target_label": label}
        if exists:
            values |= {"relationship_type": "copy", "license_status": "unknown"}
        claim_key, value = build_relationship_claim(
            "model_relationship", values, exists=exists
        )
        make_claim(
            subject,
            "model_relationship",
            value,
            ingest_source=source,
            claim_key=claim_key,
        )

    def _reconcile(self, subject):
        projection = build_through_projection(_narrowed_binding())
        assert projection is not None
        return reconcile(projection, {subject.pk})

    def test_label_edge_materializes_wording_as_data(
        self, narrowed_schema, subject, source
    ):
        self._mint(subject, source, label="several Gottlieb EM models")
        self._reconcile(subject)

        edge = ModelRelationship.objects.get(machine_model=subject)
        assert edge.target_machine is None
        assert edge.target_label == "several Gottlieb EM models"

    def test_reword_updates_the_row_in_place(
        self, narrowed_schema, subject, source, high_source
    ):
        """The stage-3 promise: a reword is an UpdateRow — same pk, so
        citations and attribution attached to the edge survive."""
        self._mint(subject, source, label="an unknown Gottlieb game")
        self._reconcile(subject)
        original_pk = ModelRelationship.objects.get(machine_model=subject).pk

        self._mint(subject, high_source, label="an unidentified 1960s Gottlieb")
        delta = self._reconcile(subject)

        edge = ModelRelationship.objects.get(machine_model=subject)
        assert edge.pk == original_pk
        assert edge.target_label == "an unidentified 1960s Gottlieb"
        assert not delta.create
        assert not delta.delete

    def test_label_tombstone_deletes_the_row(
        self, narrowed_schema, subject, source, high_source
    ):
        self._mint(subject, source, label="an unknown Gottlieb game")
        self._reconcile(subject)
        assert ModelRelationship.objects.filter(machine_model=subject).exists()

        self._mint(subject, high_source, exists=False)
        self._reconcile(subject)
        assert not ModelRelationship.objects.filter(machine_model=subject).exists()

    def test_machine_and_label_edges_coexist(self, narrowed_schema, subject, source):
        target = make_machine_model(name="Rock", slug="rock")
        self._mint(subject, source, machine=target.pk)
        self._mint(subject, source, label="whatever cabinets were available")
        self._reconcile(subject)

        edges = ModelRelationship.objects.filter(machine_model=subject)
        assert edges.count() == 2

    def test_reconcile_is_idempotent_over_null_keys(
        self, narrowed_schema, subject, source
    ):
        """The null-target row round-trips through read() as a ``None`` key —
        the honest ``int | None`` codec — so a second pass writes nothing."""
        self._mint(subject, source, label="several Gottlieb EM models")
        self._reconcile(subject)
        delta = self._reconcile(subject)
        assert delta == ([], [], [])
