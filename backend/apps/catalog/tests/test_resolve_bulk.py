"""Tests for _resolve_single, _resolve_bulk, and resolve_entity."""

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError

from apps.catalog.models import (
    Franchise,
    Location,
    MachineModel,
    Manufacturer,
    Series,
    System,
    Tag,
    Title,
)
from apps.catalog.resolve import resolve_entity
from apps.catalog.resolve._entities import _resolve_bulk, _resolve_single
from apps.catalog.resolve._helpers import get_nullable_unique_fields
from apps.catalog.tests.conftest import bulk_resolve, make_machine_model
from apps.core.models import RecordReference
from apps.provenance.models import Claim, get_claim_fields
from apps.provenance.resolution import resolve_after_mutation
from apps.provenance.test_factories import make_claim, make_ingest_source


@pytest.fixture
def opdb():
    return make_ingest_source(
        name="OPDB", slug="opdb", source_type="database", priority=200
    )


@pytest.fixture
def editorial():
    return make_ingest_source(
        name="Editorial", slug="editorial", source_type="editorial", priority=300
    )


@pytest.mark.django_db
class TestResolveBulkTitle:
    def test_resolves_multiple_titles(self, opdb):
        t1 = Title.objects.create(opdb_id="G1", name="Title One", slug="t1")
        t2 = Title.objects.create(opdb_id="G2", name="Title Two", slug="t2")

        make_claim(t1, "name", "Godzilla", ingest_source=opdb)
        make_claim(t2, "name", "Blackout", ingest_source=opdb)

        _resolve_bulk(Title, get_claim_fields(Title))

        t1.refresh_from_db()
        t2.refresh_from_db()
        assert t1.name == "Godzilla"
        assert t2.name == "Blackout"

    def test_winner_by_priority(self, opdb, editorial):
        t = Title.objects.create(opdb_id="G1", name="Placeholder", slug="t1")

        make_claim(t, "name", "Low Priority", ingest_source=opdb)
        make_claim(t, "name", "High Priority", ingest_source=editorial)

        _resolve_bulk(Title, get_claim_fields(Title))

        t.refresh_from_db()
        assert t.name == "High Priority"

    def test_no_claims_resets_to_default(self, opdb):
        t = Title.objects.create(
            opdb_id="G1", name="Stale Name", slug="t1", description="Stale desc"
        )

        # Name claim to satisfy the NOT-blank constraint; no description claim.
        make_claim(t, "name", "Stale Name", ingest_source=opdb)
        _resolve_bulk(Title, get_claim_fields(Title))

        t.refresh_from_db()
        assert t.description == ""  # Non-constrained field resets to default.

    def test_fk_resolves_franchise(self, opdb):
        from apps.catalog.resolve import resolve_all_entities

        franchise = Franchise.objects.create(name="Godzilla", slug="godzilla")
        t = Title.objects.create(opdb_id="G1", name="Placeholder", slug="t1")

        make_claim(t, "name", "Godzilla", ingest_source=opdb)
        make_claim(t, "franchise", "godzilla", ingest_source=opdb)

        resolve_all_entities(Title)

        t.refresh_from_db()
        assert t.franchise == franchise

    def test_fk_resolves_series(self, opdb):
        from apps.catalog.resolve import resolve_all_entities

        series = Series.objects.create(name="Godzilla Line", slug="godzilla-line")
        t = Title.objects.create(opdb_id="G1", name="Placeholder", slug="t1")

        make_claim(t, "name", "Godzilla", ingest_source=opdb)
        make_claim(t, "series", "godzilla-line", ingest_source=opdb)

        resolve_all_entities(Title)

        t.refresh_from_db()
        assert t.series == series

    def test_fk_resets_when_no_claim(self, opdb):
        from apps.catalog.resolve import resolve_all_entities

        franchise = Franchise.objects.create(name="Godzilla", slug="godzilla")
        t = Title.objects.create(
            opdb_id="G1", name="Placeholder", slug="t1", franchise=franchise
        )

        # Name claim but no franchise claim — franchise should reset to None.
        make_claim(t, "name", "Godzilla", ingest_source=opdb)
        resolve_all_entities(Title)

        t.refresh_from_db()
        assert t.franchise is None

    def test_series_fk_resets_when_no_claim(self, opdb):
        from apps.catalog.resolve import resolve_all_entities

        series = Series.objects.create(name="Godzilla Line", slug="godzilla-line")
        t = Title.objects.create(
            opdb_id="G1", name="Placeholder", slug="t1", series=series
        )

        # Name claim but no series claim — series should reset to None.
        make_claim(t, "name", "Godzilla", ingest_source=opdb)
        resolve_all_entities(Title)

        t.refresh_from_db()
        assert t.series is None

    def test_object_ids_scoping(self, opdb):
        t1 = Title.objects.create(opdb_id="G1", name="Untouched", slug="t1")
        t2 = Title.objects.create(opdb_id="G2", name="Placeholder", slug="t2")

        make_claim(t2, "name", "Resolved", ingest_source=opdb)

        # Only resolve t2.
        _resolve_bulk(Title, get_claim_fields(Title), object_ids={t2.pk})

        t1.refresh_from_db()
        t2.refresh_from_db()
        assert t1.name == "Untouched"  # Not touched.
        assert t2.name == "Resolved"

    def test_updated_at_is_set(self, opdb):
        t = Title.objects.create(opdb_id="G1", name="Placeholder", slug="t1")
        old_updated_at = t.updated_at

        make_claim(t, "name", "New Name", ingest_source=opdb)
        _resolve_bulk(Title, get_claim_fields(Title))

        t.refresh_from_db()
        assert t.updated_at > old_updated_at


@pytest.mark.django_db
class TestResolveBulkManufacturer:
    def test_resolves_with_int_fields(self, opdb):
        from apps.catalog.models import CorporateEntity

        m = Manufacturer.objects.create(name="Stern Pinball", slug="stern")
        ce = CorporateEntity.objects.create(
            manufacturer=m, name="Stern Pinball, Inc.", slug="stern-pinball-inc"
        )

        make_claim(ce, "name", "Stern Pinball, Inc.", ingest_source=opdb)
        make_claim(ce, "year_start", "1999", ingest_source=opdb)

        _resolve_bulk(
            CorporateEntity,
            get_claim_fields(CorporateEntity),
        )

        ce.refresh_from_db()
        assert ce.name == "Stern Pinball, Inc."
        assert ce.year_start == 1999


@pytest.mark.django_db
class TestResolveBulkMarkdownReferences:
    def test_bulk_resolve_syncs_record_references(self, opdb):
        """_resolve_bulk populates RecordReference for markdown link fields."""
        mfr = Manufacturer.objects.create(name="Williams", slug="williams")
        system = System.objects.create(name="WPC-95", slug="wpc-95", manufacturer=mfr)

        make_claim(mfr, "name", "Williams", ingest_source=opdb)
        make_claim(
            mfr,
            "description",
            f"Uses [[system:id:{system.pk}]].",
            ingest_source=opdb,
        )

        _resolve_bulk(Manufacturer, get_claim_fields(Manufacturer))

        mfr_ct = ContentType.objects.get_for_model(Manufacturer)
        refs = RecordReference.objects.filter(source_type=mfr_ct, source_id=mfr.pk)
        assert refs.count() == 1
        system_ct = ContentType.objects.get_for_model(System)
        ref = refs.first()
        assert ref is not None
        assert ref.target_type == system_ct
        assert ref.target_id == system.pk

    def test_bulk_resolve_cleans_stale_references(self, opdb):
        """_resolve_bulk removes RecordReference when markdown links are removed."""
        mfr = Manufacturer.objects.create(name="Williams", slug="williams")
        system = System.objects.create(name="WPC-95", slug="wpc-95", manufacturer=mfr)

        # First resolve with a link
        make_claim(
            mfr,
            "description",
            f"Uses [[system:id:{system.pk}]].",
            ingest_source=opdb,
        )
        _resolve_bulk(Manufacturer, get_claim_fields(Manufacturer))

        mfr_ct = ContentType.objects.get_for_model(Manufacturer)
        assert (
            RecordReference.objects.filter(source_type=mfr_ct, source_id=mfr.pk).count()
            == 1
        )

        # Deactivate the claim so description resolves to blank
        Claim.objects.filter(
            content_type=mfr_ct, object_id=mfr.pk, field_name="description"
        ).update(is_active=False)
        _resolve_bulk(Manufacturer, get_claim_fields(Manufacturer))

        assert (
            RecordReference.objects.filter(source_type=mfr_ct, source_id=mfr.pk).count()
            == 0
        )


@pytest.mark.django_db
class TestResolveBulkUniqueFieldSafety:
    """UNIQUE fields must not be reset when no claim exists, or bulk_update
    will crash with an IntegrityError when multiple objects share the default."""

    def test_unique_name_preserved_when_no_claim(self, opdb):
        """Objects without a name claim keep their existing name."""
        from apps.catalog.models import Theme

        t1 = Theme.objects.create(name="Horror", slug="horror")
        t2 = Theme.objects.create(name="Sports", slug="sports")

        # Only t1 gets a name claim; t2 has none.
        make_claim(t1, "name", "Horror Movies", ingest_source=opdb)

        _resolve_bulk(Theme, get_claim_fields(Theme))

        t1.refresh_from_db()
        t2.refresh_from_db()
        assert t1.name == "Horror Movies"  # Updated by claim.
        assert t2.name == "Sports"  # Preserved — not reset to "".

    def test_non_unique_field_still_resets(self, opdb):
        """Non-unique fields are still reset to default when no claim exists."""
        from apps.catalog.models import Theme

        t = Theme.objects.create(name="Horror", slug="horror", description="Old desc")

        # Name claim but no description claim.
        make_claim(t, "name", "Horror", ingest_source=opdb)

        _resolve_bulk(Theme, get_claim_fields(Theme))

        t.refresh_from_db()
        assert t.description == ""  # Reset to default.

    def test_single_preserves_unique_name_without_claim(self, opdb):
        """_resolve_single also preserves UNIQUE fields without claims (parity)."""
        from apps.catalog.models import Theme

        t = Theme.objects.create(name="Horror", slug="horror", description="Old desc")

        # Description claim but no name claim.
        make_claim(t, "description", "Scary stuff", ingest_source=opdb)

        _resolve_single(t, get_claim_fields(Theme))

        assert t.name == "Horror"  # Preserved — not reset to "".
        assert t.description == "Scary stuff"  # Applied from claim.

    def test_single_and_bulk_produce_same_result(self, opdb):
        """Single and bulk resolution must agree on partial-claim entities."""
        from apps.catalog.models import Theme

        # Two identical themes, one resolved single, one bulk.
        t_single = Theme.objects.create(
            name="Horror", slug="horror", description="Old desc"
        )
        t_bulk = Theme.objects.create(
            name="Horror Copy", slug="horror-copy", description="Old desc"
        )

        # Both get only a description claim, no name claim.
        make_claim(t_single, "description", "Scary stuff", ingest_source=opdb)
        make_claim(t_bulk, "description", "Scary stuff", ingest_source=opdb)

        _resolve_single(t_single, get_claim_fields(Theme))
        t_single.save()

        _resolve_bulk(Theme, get_claim_fields(Theme), object_ids={t_bulk.pk})
        t_bulk.refresh_from_db()

        assert t_single.name == "Horror"  # Preserved.
        assert t_bulk.name == "Horror Copy"  # Preserved.
        assert t_single.description == t_bulk.description == "Scary stuff"


@pytest.mark.django_db
class TestPreserveNotNullFK:
    """Non-nullable FK fields must not be reset when no claim exists."""

    @pytest.fixture
    def subgen_fields(self):
        """Claim fields including technology_generation (NOT NULL FK).

        Uses explicit field dict rather than get_claim_fields() so these
        tests verify resolver behavior independent of claims_exempt state.
        """
        from apps.catalog.models.taxonomy import TechnologySubgeneration

        fields = get_claim_fields(TechnologySubgeneration)
        fields["technology_generation"] = "technology_generation"
        return fields

    def test_bulk_preserves_notnull_fk_without_claim(self, opdb, subgen_fields):
        from apps.catalog.models.taxonomy import (
            TechnologyGeneration,
            TechnologySubgeneration,
        )

        gen = TechnologyGeneration.objects.create(
            name="Solid State", slug="solid-state"
        )
        subgen = TechnologySubgeneration.objects.create(
            name="Discrete Logic", slug="discrete-logic", technology_generation=gen
        )

        # Name claim but no technology_generation claim.
        make_claim(subgen, "name", "Discrete Logic", ingest_source=opdb)

        _resolve_bulk(
            TechnologySubgeneration,
            subgen_fields,
            object_ids={subgen.pk},
        )

        subgen.refresh_from_db()
        assert subgen.name == "Discrete Logic"
        assert subgen.technology_generation == gen  # Preserved, not crashed.

    def test_single_preserves_notnull_fk_without_claim(self, opdb, subgen_fields):
        from apps.catalog.models.taxonomy import (
            TechnologyGeneration,
            TechnologySubgeneration,
        )

        gen = TechnologyGeneration.objects.create(
            name="Solid State", slug="solid-state"
        )
        subgen = TechnologySubgeneration.objects.create(
            name="Discrete Logic", slug="discrete-logic", technology_generation=gen
        )

        make_claim(subgen, "name", "Discrete Logic", ingest_source=opdb)

        _resolve_single(subgen, subgen_fields)
        subgen.save()

        subgen.refresh_from_db()
        assert subgen.technology_generation == gen  # Preserved.

    def test_notnull_fk_overwritten_when_claim_exists(self, opdb, subgen_fields):
        from apps.catalog.models.taxonomy import (
            TechnologyGeneration,
            TechnologySubgeneration,
        )

        gen1 = TechnologyGeneration.objects.create(
            name="Solid State", slug="solid-state"
        )
        gen2 = TechnologyGeneration.objects.create(name="Electromechanical", slug="em")
        subgen = TechnologySubgeneration.objects.create(
            name="Discrete Logic", slug="discrete-logic", technology_generation=gen1
        )

        make_claim(subgen, "name", "Discrete Logic", ingest_source=opdb)
        make_claim(subgen, "technology_generation", "em", ingest_source=opdb)

        _resolve_bulk(
            TechnologySubgeneration,
            subgen_fields,
            object_ids={subgen.pk},
        )

        subgen.refresh_from_db()
        assert subgen.technology_generation == gen2  # Overwritten by claim.


@pytest.mark.django_db
class TestResolveBulkTaxonomy:
    def test_malformed_int_claim_rejected_at_boundary(self, opdb):
        """Invalid integer values are now rejected by assert_claim validation."""
        from django.core.exceptions import ValidationError

        tag = Tag.objects.create(name="Test Tag", slug="test-tag")

        make_claim(tag, "name", "Test Tag", ingest_source=opdb)
        with pytest.raises(ValidationError, match="must be an integer"):
            make_claim(tag, "display_order", "abc", ingest_source=opdb)


@pytest.mark.django_db
class TestResolveTitle:
    def test_single_object_wrapper(self, opdb):
        franchise = Franchise.objects.create(name="Godzilla", slug="godzilla")
        t = Title.objects.create(opdb_id="G1", name="Placeholder", slug="t1")

        make_claim(t, "name", "Godzilla", ingest_source=opdb)
        make_claim(t, "description", "A monster game.", ingest_source=opdb)
        make_claim(t, "franchise", "godzilla", ingest_source=opdb)

        result = resolve_entity(t)

        assert result.name == "Godzilla"
        assert result.description == "A monster game."
        assert result.franchise == franchise

    def test_single_object_wrapper_resolves_series(self, opdb):
        series = Series.objects.create(name="Godzilla Line", slug="godzilla-line")
        t = Title.objects.create(opdb_id="G1", name="Placeholder", slug="t1")

        make_claim(t, "name", "Godzilla", ingest_source=opdb)
        make_claim(t, "description", "A monster game.", ingest_source=opdb)
        make_claim(t, "series", "godzilla-line", ingest_source=opdb)

        result = resolve_entity(t)

        assert result.name == "Godzilla"
        assert result.description == "A monster game."
        assert result.series == series

    def test_resets_franchise_when_no_claim(self, opdb):
        franchise = Franchise.objects.create(name="Godzilla", slug="godzilla")
        t = Title.objects.create(
            opdb_id="G1", name="Placeholder", slug="t1", franchise=franchise
        )

        # Only a name claim, no franchise.
        make_claim(t, "name", "Godzilla", ingest_source=opdb)
        result = resolve_entity(t)

        assert result.franchise is None

    def test_resets_series_when_no_claim(self, opdb):
        series = Series.objects.create(name="Godzilla Line", slug="godzilla-line")
        t = Title.objects.create(
            opdb_id="G1", name="Placeholder", slug="t1", series=series
        )

        # Only a name claim, no series.
        make_claim(t, "name", "Godzilla", ingest_source=opdb)
        result = resolve_entity(t)

        assert result.series is None


@pytest.mark.django_db
class TestSlugConflictDetection:
    """Slug conflict detection reverts losers to pre-resolution slugs."""

    @pytest.fixture
    def title_fields_with_slug(self):
        """Claim fields including slug, stated explicitly for these resolver tests."""
        fields = get_claim_fields(Title)
        fields["slug"] = "slug"
        return fields

    def test_bulk_slug_conflict_reverts_loser(self, opdb, title_fields_with_slug):
        t1 = Title.objects.create(name="First", slug="target-slug")
        t2 = Title.objects.create(name="Second", slug="original-slug")

        make_claim(t1, "name", "First", ingest_source=opdb)
        make_claim(t1, "slug", "target-slug", ingest_source=opdb)
        make_claim(t2, "name", "Second", ingest_source=opdb)
        # t2 claims the same slug as t1.
        make_claim(t2, "slug", "target-slug", ingest_source=opdb)

        _resolve_bulk(Title, title_fields_with_slug)

        t1.refresh_from_db()
        t2.refresh_from_db()
        assert t1.slug == "target-slug"  # First wins.
        assert t2.slug == "original-slug"  # Reverted to pre-resolution slug.

    def test_preserver_wins_over_changer(self, opdb, title_fields_with_slug):
        """When A claims B's existing slug and B has no slug claim, B keeps it."""
        t1 = Title.objects.create(name="Changer", slug="alpha")
        t2 = Title.objects.create(name="Preserver", slug="beta")

        make_claim(t1, "name", "Changer", ingest_source=opdb)
        # t1 claims t2's slug — t1 is the changer.
        make_claim(t1, "slug", "beta", ingest_source=opdb)
        make_claim(t2, "name", "Preserver", ingest_source=opdb)
        # t2 has no slug claim — preserved by preserve_when_unclaimed.

        _resolve_bulk(Title, title_fields_with_slug)

        t1.refresh_from_db()
        t2.refresh_from_db()
        assert t2.slug == "beta"  # Preserver wins — it had this slug all along.
        assert t1.slug == "alpha"  # Changer reverts to its original slug.

    def test_no_conflict_when_slugs_differ(self, opdb, title_fields_with_slug):
        t1 = Title.objects.create(name="First", slug="slug-a")
        t2 = Title.objects.create(name="Second", slug="slug-b")

        make_claim(t1, "name", "First", ingest_source=opdb)
        make_claim(t1, "slug", "slug-a", ingest_source=opdb)
        make_claim(t2, "name", "Second", ingest_source=opdb)
        make_claim(t2, "slug", "slug-b", ingest_source=opdb)

        _resolve_bulk(Title, title_fields_with_slug)

        t1.refresh_from_db()
        t2.refresh_from_db()
        assert t1.slug == "slug-a"
        assert t2.slug == "slug-b"

    def test_single_object_slug_conflict_raises(self, opdb):
        """A single-object slug collision fails loud at the DB constraint.

        Resolution leaves cross-reference uniqueness to the DB rather than
        silently reverting the loser. ``resolve_entity`` saves the winning claim
        and the unique constraint raises IntegrityError, which ``execute_claims``
        turns into a 422 on the interactive path.
        """
        # Owner holds "taken-slug" in the DB.
        Title.objects.create(name="Owner", slug="taken-slug")
        t2 = Title.objects.create(name="Challenger", slug="original-slug")

        make_claim(t2, "name", "Challenger", ingest_source=opdb)
        make_claim(t2, "slug", "taken-slug", ingest_source=opdb)

        with pytest.raises(IntegrityError):
            resolve_entity(t2)


class TestNullableUniqueFieldDiscovery:
    """get_nullable_unique_fields covers single-column unique IDs only."""

    def test_machine_model_external_ids(self):
        fields = get_nullable_unique_fields(
            MachineModel, get_claim_fields(MachineModel)
        )
        assert fields == ["ipdb_id", "opdb_id", "pinside_id"]

    def test_excludes_composite_constraint_member(self):
        """Location.parent is nullable and in (parent, slug) — must NOT appear.

        Clearing it on de-confliction would wrongly null sibling locations'
        parents. The helper tests field.unique only, never composite membership.
        """
        fields = get_nullable_unique_fields(Location, get_claim_fields(Location))
        assert "parent" not in fields


@pytest.mark.django_db
class TestNullableUniqueConflictDetection:
    """Bulk de-confliction of every nullable single-column UNIQUE field.

    The bulk path resolves an in-batch collision on a nullable unique field by
    clearing the loser to ``None`` (first-encountered, by queryset ordering,
    wins) rather than aborting the whole batch with ``IntegrityError``. This is
    discovered by introspection, so it covers every external-ID field, not just
    MachineModel ``opdb_id``.
    """

    def test_bulk_opdb_id_conflict_clears_loser(self, opdb):
        """MachineModel opdb_id collision: one keeps it, the loser clears."""
        mm1 = make_machine_model(name="Alpha", slug="alpha")
        mm2 = make_machine_model(name="Beta", slug="beta")
        make_claim(mm1, "opdb_id", "GCONFLICT-1", ingest_source=opdb)
        make_claim(mm2, "opdb_id", "GCONFLICT-1", ingest_source=opdb)

        _resolve_bulk(MachineModel, get_claim_fields(MachineModel))

        mm1.refresh_from_db()
        mm2.refresh_from_db()
        winners = [m for m in (mm1, mm2) if m.opdb_id == "GCONFLICT-1"]
        losers = [m for m in (mm1, mm2) if m.opdb_id is None]
        assert len(winners) == 1
        assert len(losers) == 1

    def test_bulk_non_mm_unique_id_conflict_clears_loser(self, opdb):
        """Manufacturer wikidata_id collision exercises the introspection path.

        wikidata_id was never de-conflicted in bulk before — the loser used to
        abort the batch. Now the loser clears to None like opdb_id.
        """
        m1 = Manufacturer.objects.create(name="Stern", slug="stern")
        m2 = Manufacturer.objects.create(name="Bally", slug="bally")
        make_claim(m1, "name", "Stern", ingest_source=opdb)
        make_claim(m1, "wikidata_id", "Q123", ingest_source=opdb)
        make_claim(m2, "name", "Bally", ingest_source=opdb)
        make_claim(m2, "wikidata_id", "Q123", ingest_source=opdb)

        _resolve_bulk(Manufacturer, get_claim_fields(Manufacturer))

        m1.refresh_from_db()
        m2.refresh_from_db()
        winners = [m for m in (m1, m2) if m.wikidata_id == "Q123"]
        losers = [m for m in (m1, m2) if m.wikidata_id is None]
        assert len(winners) == 1
        assert len(losers) == 1

    def test_no_conflict_when_ids_differ(self, opdb):
        """Distinct nullable-unique values are left untouched."""
        mm1 = make_machine_model(name="Alpha", slug="alpha")
        mm2 = make_machine_model(name="Beta", slug="beta")
        make_claim(mm1, "opdb_id", "GA-1", ingest_source=opdb)
        make_claim(mm2, "opdb_id", "GB-2", ingest_source=opdb)

        _resolve_bulk(MachineModel, get_claim_fields(MachineModel))

        mm1.refresh_from_db()
        mm2.refresh_from_db()
        assert mm1.opdb_id == "GA-1"
        assert mm2.opdb_id == "GB-2"


@pytest.mark.django_db
class TestApplyResolutionPreserve:
    """Single-object resolution preserves UNIQUE fields when no claim exists."""

    def test_preserves_slug_without_claim(self, opdb):
        mm = make_machine_model(name="Test", slug="test-slug")
        make_claim(mm, "name", "Test Model", ingest_source=opdb)
        # No slug claim — slug should be preserved after resolution.

        resolve_after_mutation(mm)

        mm.refresh_from_db()
        assert mm.slug == "test-slug"  # Preserved.
        assert mm.name == "Test Model"  # Resolved from claim.

    def test_preserves_opdb_id_without_claim(self, opdb):
        mm = make_machine_model(name="Test", slug="test-slug", opdb_id="O123")
        make_claim(mm, "name", "Test Model", ingest_source=opdb)
        # No opdb_id claim.

        resolve_after_mutation(mm)

        mm.refresh_from_db()
        assert mm.opdb_id == "O123"  # Preserved.

    def test_bulk_preserves_slug_without_claim(self, opdb):
        mm1 = make_machine_model(name="A", slug="a-slug")
        mm2 = make_machine_model(name="B", slug="b-slug")
        make_claim(mm1, "name", "Model A", ingest_source=opdb)
        make_claim(mm2, "name", "Model B", ingest_source=opdb)
        # No slug claims — both should preserve their slugs.

        bulk_resolve()

        mm1.refresh_from_db()
        mm2.refresh_from_db()
        assert mm1.slug == "a-slug"
        assert mm2.slug == "b-slug"
