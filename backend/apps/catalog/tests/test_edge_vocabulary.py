"""The relationship-filter key vocabulary: registry shape, parsing and the
per-key membership predicates, including the deliberate liveness asymmetry
(outbound ignores the far end; inbound requires it live)."""

from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.catalog.api._edge_vocabulary import (
    EDGE_KEYS,
    EdgeSelection,
    _lineage_field_names,
    edge_q,
    edge_wire_value,
    parse_edge_value,
)
from apps.catalog.models import (
    LicenseStatus,
    MachineModel,
    RelationshipType,
    SelfFkRole,
    Title,
)
from apps.catalog.tests.conftest import make_machine_model
from apps.catalog.tests.game_builders import _edge, _model, _title

pytestmark = pytest.mark.django_db


def _matches(value: str) -> set[str]:
    """Slugs of every MachineModel (any status) matching the parsed *value* —
    the raw predicate, no listing candidate-set narrowing."""
    selection = parse_edge_value(value)
    assert selection is not None
    return set(
        MachineModel.objects.filter(edge_q(selection)).values_list("slug", flat=True)
    )


class TestRegistry:
    def test_the_closed_key_set(self):
        """The whole vocabulary, pinned — what the public API actually ships.
        A new RelationshipType member lands here automatically, and a self-FK
        classified as lineage lands here once classified; this test failing is
        the prompt to decide its filter labels and facet entry, not a bug."""
        assert set(EDGE_KEYS) == {
            "variant_of",
            "remake_of",
            "export_edition_of",
            "conversion",
            "conversion_kit",
            "copy",
            "retheme",
            "bootleg",
            "licensed_build",
        }

    def test_every_relationship_type_is_a_key(self):
        """The type keys are iterated from the enum, so a new type reaches
        the vocabulary without being described a second time."""
        assert {t.value for t in RelationshipType} <= set(EDGE_KEYS)

    @pytest.mark.parametrize(
        ("roles", "named"),
        [
            (
                {"variant_of": SelfFkRole.LINEAGE, "remake_of": SelfFkRole.LINEAGE},
                "export_edition_of",
            ),
            (
                {
                    "variant_of": SelfFkRole.LINEAGE,
                    "remake_of": SelfFkRole.LINEAGE,
                    "export_edition_of": SelfFkRole.LINEAGE,
                    "merged_into": SelfFkRole.ADMINISTRATIVE,
                },
                "merged_into",
            ),
        ],
        ids=["undeclared", "stale"],
    )
    def test_the_roles_must_match_the_model(
        self,
        monkeypatch: pytest.MonkeyPatch,
        roles: dict[str, SelfFkRole],
        named: str,
    ):
        """The gate: filterability is a product decision, so a self-FK with no
        verdict — or a verdict for a field that no longer exists — fails by
        name instead of silently entering the published filter vocabulary."""
        monkeypatch.setattr(MachineModel, "self_fk_roles", roles)
        with pytest.raises(ImproperlyConfigured, match=named):
            _lineage_field_names()

    def test_an_administrative_self_fk_is_not_a_key(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """The negative verdict is the point of the declaration: an
        administrative self-reference stays out of the vocabulary."""
        monkeypatch.setattr(
            MachineModel,
            "self_fk_roles",
            {
                **MachineModel.self_fk_roles,
                "export_edition_of": SelfFkRole.ADMINISTRATIVE,
            },
        )
        assert "export_edition_of" not in _lineage_field_names()


class TestParsing:
    @pytest.mark.parametrize("key", sorted(EDGE_KEYS))
    def test_roundtrip_both_directions(self, key: str):
        for direction in ("out", "in"):
            selection = EdgeSelection(key, direction)
            assert parse_edge_value(edge_wire_value(selection)) == selection

    @pytest.mark.parametrize(
        "value",
        ["", "bogus", "bogus:in", "copy:out", "copy:IN", "Copy", "copy :in", ":in"],
    )
    def test_unknown_or_malformed_is_none(self, value: str):
        assert parse_edge_value(value) is None


class TestTypedEdgePredicates:
    @pytest.fixture
    def graph(self):
        """An original that has been copied (unlicensed), converted and
        kitted; a licensed copy; a label-only kit with no seeded donor."""
        t_orig = _title("Original", "original")
        original = _model(t_orig, "original")
        t_others = _title("Others", "others")
        bootlegger = _model(t_others, "bootlegger")
        converter = _model(t_others, "converter")
        kit = _model(t_others, "kit")
        licensee = _model(t_others, "licensee")
        label_kit = _model(t_others, "label-kit")
        _edge(
            bootlegger,
            original,
            RelationshipType.COPY,
            license_status=LicenseStatus.UNLICENSED,
        )
        _edge(converter, original, RelationshipType.CONVERSION)
        _edge(kit, original, RelationshipType.CONVERSION_KIT)
        _edge(
            licensee,
            original,
            RelationshipType.COPY,
            license_status=LicenseStatus.LICENSED,
        )
        _edge(
            label_kit,
            None,
            RelationshipType.CONVERSION_KIT,
            target_label="Unseeded Donor",
        )
        return original

    def test_outbound_by_type(self, graph: MachineModel):
        assert _matches("copy") == {"bootlegger", "licensee"}
        assert _matches("conversion") == {"converter"}
        assert _matches("conversion_kit") == {"kit", "label-kit"}
        assert _matches("retheme") == set()

    def test_composites_are_licensing_cells(self, graph: MachineModel):
        """bootleg/licensed_build are subsets of copy; an unknown-status copy
        matches neither composite."""
        _edge(
            _model(Title.objects.get(slug="others"), "unknown-copy"),
            graph,
            RelationshipType.COPY,
        )
        assert _matches("copy") == {"bootlegger", "licensee", "unknown-copy"}
        assert _matches("bootleg") == {"bootlegger"}
        assert _matches("licensed_build") == {"licensee"}

    def test_inbound_by_type(self, graph: MachineModel):
        assert _matches("copy:in") == {"original"}
        assert _matches("bootleg:in") == {"original"}
        assert _matches("licensed_build:in") == {"original"}
        assert _matches("conversion:in") == {"original"}
        assert _matches("conversion_kit:in") == {"original"}
        assert _matches("retheme:in") == set()

    def test_label_only_edges_count_outbound_only(self, graph: MachineModel):
        """A free-text donor has no catalog record: the subject still is a
        kit, and no record gains the inbound fact."""
        assert "label-kit" in _matches("conversion_kit")
        assert _matches("conversion_kit:in") == {"original"}

    def test_outbound_survives_a_deleted_target(self, graph: MachineModel):
        """The fact is recorded about the subject; deleting the donor's
        record does not stop the copy being a copy."""
        graph.status = "deleted"
        graph.save(update_fields=["status"])
        assert _matches("copy") == {"bootlegger", "licensee"}

    def test_inbound_drops_a_deleted_subject(self, graph: MachineModel):
        bootlegger = MachineModel.objects.get(slug="bootlegger")
        bootlegger.status = "deleted"
        bootlegger.save(update_fields=["status"])
        assert _matches("bootleg:in") == set()
        # The other copy edge (licensed) still backs copy:in.
        assert _matches("copy:in") == {"original"}

    def test_inbound_drops_a_deleted_subject_title(self, graph: MachineModel):
        """A live Model under a deleted Title is invisible everywhere in the
        listing, so it must not back an inbound fact either."""
        others = Title.objects.get(slug="others")
        others.status = "deleted"
        others.save(update_fields=["status"])
        assert _matches("copy:in") == set()


class TestLineagePredicates:
    @pytest.fixture
    def graph(self):
        t = _title("Family", "family")
        parent = _model(t, "parent")
        _model(t, "variant", variant_of=parent)
        make_machine_model(title=t, name="remake", slug="remake", remake_of=parent)
        make_machine_model(
            title=t, name="export", slug="export", export_edition_of=parent
        )
        return parent

    def test_outbound(self, graph: MachineModel):
        assert _matches("variant_of") == {"variant"}
        assert _matches("remake_of") == {"remake"}
        assert _matches("export_edition_of") == {"export"}

    def test_inbound(self, graph: MachineModel):
        assert _matches("variant_of:in") == {"parent"}
        assert _matches("remake_of:in") == {"parent"}
        assert _matches("export_edition_of:in") == {"parent"}

    def test_outbound_survives_a_deleted_parent(self, graph: MachineModel):
        graph.status = "deleted"
        graph.save(update_fields=["status"])
        assert _matches("variant_of") == {"variant"}

    def test_inbound_drops_a_deleted_far_end(self, graph: MachineModel):
        variant = MachineModel.objects.get(slug="variant")
        variant.status = "deleted"
        variant.save(update_fields=["status"])
        assert _matches("variant_of:in") == set()
        # The other lineage children still back their own keys.
        assert _matches("remake_of:in") == {"parent"}

    def test_inbound_drops_a_deleted_far_end_title(self):
        """Lineage crosses Titles for remakes/exports; a far-end child whose
        whole Title is deleted must not back the inbound fact."""
        original = _model(_title("Solo", "solo"), "solo-original")
        t_remakes = _title("Remakes", "remakes")
        make_machine_model(
            title=t_remakes, name="Cross", slug="cross-remake", remake_of=original
        )
        assert _matches("remake_of:in") == {"solo-original"}
        t_remakes.status = "deleted"
        t_remakes.save(update_fields=["status"])
        assert _matches("remake_of:in") == set()
