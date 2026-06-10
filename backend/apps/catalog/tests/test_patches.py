"""Tests for the data-patch adapter and the ingest_patches command."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.catalog.claims import build_relationship_claim
from apps.catalog.ingestion.apply import RunReport, apply_plan
from apps.catalog.ingestion.patches import (
    PatchError,
    build_plan,
    fingerprint,
    load_patch,
    parse_patch_text,
)
from apps.catalog.models import (
    CorporateEntity,
    CorporateEntityLocation,
    Location,
    Manufacturer,
    Tag,
)
from apps.catalog.resolve import resolve_all_corporate_entity_locations
from apps.citation.models import CitationSource, CitationSourceLink
from apps.provenance.models import ChangeSet, CitationInstance, Claim, IngestRun, Source

pytestmark = pytest.mark.django_db


def _apply(
    text: str, *, patch_id: str = "0001-test", dry_run: bool = False
) -> RunReport:
    """Build + apply a patch from text (bypassing file discovery + ledger)."""
    doc = load_patch(text)
    source = Source.objects.get(slug=doc.attribution)
    plan = build_plan(doc, source=source, patch_id=patch_id)
    return apply_plan(plan, dry_run=dry_run)


# ── Parsing / strict loader ────────────────────────────────────────


def test_duplicate_mapping_key_rejected():
    with pytest.raises(PatchError):
        load_patch("attribution: a\nattribution: b\nclaims: []\n")


def test_unquoted_date_stays_string():
    """The restricted loader prevents YAML implicit coercion (no date type)."""
    data = parse_patch_text("a: 1996-01-01\nb: no\nc: 5\nd: true\n")
    assert data["a"] == "1996-01-01"
    assert data["b"] == "no"
    assert data["c"] == 5
    assert data["d"] is True


def test_explicit_non_json_tag_rejected():
    with pytest.raises(PatchError):
        parse_patch_text("a: !!timestamp 2020-01-01\n")


def test_non_finite_float_rejected():
    # !!float .nan / .inf produce non-finite floats that aren't valid JSON.
    for tag in ("!!float .nan", "!!float .inf", "!!float -.inf"):
        with pytest.raises(PatchError, match="non-finite"):
            parse_patch_text(f"a: {tag}\n")


def test_fingerprint_stable_to_key_order_and_whitespace():
    a = parse_patch_text("attribution: x\nclaims:\n  - model.a: {year: 1}\n")
    b = parse_patch_text("claims:\n  - model.a: {year: 1}\nattribution:   x\n")
    assert fingerprint(a) == fingerprint(b)


def test_fingerprint_changes_with_value():
    a = parse_patch_text("attribution: x\nclaims:\n  - model.a: {year: 1}\n")
    b = parse_patch_text("attribution: x\nclaims:\n  - model.a: {year: 2}\n")
    assert fingerprint(a) != fingerprint(b)


# ── Edit: scalar + relationship ────────────────────────────────────


def test_edit_scalar_and_tag(machine_model):
    Tag.objects.create(name="Prototype", slug="prototype")
    text = f"""
attribution: flip-museum
description: tag a prototype
claims:
  - model.{machine_model.slug}:
      year: 1990
      tag: [prototype]
"""
    report = _apply(text)
    assert report.rejected == 0

    machine_model.refresh_from_db()
    assert machine_model.year == 1990
    assert list(machine_model.tags.values_list("slug", flat=True)) == ["prototype"]

    tag_claim = Claim.objects.get(field_name="tag", is_active=True)
    # Namespace key 'tag' resolves directly (no plural→singular bridge).
    assert tag_claim.claim_key.startswith("tag")
    assert tag_claim.source is not None
    assert tag_claim.source.slug == "flip-museum"


def test_unknown_field_rejected(machine_model):
    text = f"""
attribution: flip-museum
claims:
  - model.{machine_model.slug}:
      not_a_field: 5
"""
    with pytest.raises(PatchError, match="unknown field"):
        _apply(text)


def test_unknown_entity_type_rejected():
    text = """
attribution: flip-museum
claims:
  - frobnicator.foo:
      year: 1
"""
    with pytest.raises(PatchError):
        _apply(text)


# ── Create ─────────────────────────────────────────────────────────


def test_create_manufacturer():
    text = """
attribution: flip-museum
description: new brand
claims:
  - manufacturer.acme-pinball:
      name: Acme Pinball
      create: true
"""
    report = _apply(text, patch_id="0001-acme")
    assert report.records_created == 1

    mfr = Manufacturer.objects.get(slug="acme-pinball")
    assert mfr.name == "Acme Pinball"
    # Matching claims for the create contract (slug + name + status).
    keys = set(
        Claim.objects.filter(source__slug="flip-museum", is_active=True).values_list(
            "field_name", flat=True
        )
    )
    assert {"slug", "name", "status"} <= keys


def test_create_when_already_exists_errors(manufacturer):
    text = f"""
attribution: flip-museum
claims:
  - manufacturer.{manufacturer.slug}:
      name: Dup
      create: true
"""
    with pytest.raises(PatchError, match="already exists"):
        _apply(text)


def test_create_rejects_authored_public_id_field():
    # slug comes from the entity reference; authoring it (even a mismatch that
    # would silently create the wrong entity) is rejected.
    text = """
attribution: flip-museum
claims:
  - manufacturer.acme:
      create: true
      slug: other
      name: Acme
"""
    with pytest.raises(PatchError, match="do not set"):
        _apply(text)


def test_create_rejects_authored_status():
    text = """
attribution: flip-museum
claims:
  - manufacturer.acme:
      create: true
      status: deleted
      name: Acme
"""
    with pytest.raises(PatchError, match="do not set"):
        _apply(text)


def _country(path: str, name: str) -> Location:
    return Location.objects.create(
        location_path=path, slug=path, name=name, location_type="country"
    )


def test_create_location():
    # Location.location_path is derived from parent + slug; the author writes
    # the slug + parent claims and the adapter composes the path from them,
    # verifying it against the entity reference.
    usa = _country("usa", "USA")
    Location.objects.create(
        location_path="usa/tx",
        slug="tx",
        name="Texas",
        location_type="state",
        parent=usa,
    )
    text = """
attribution: flip-museum
claims:
  - location.usa/tx/paris:
      create: true
      name: Paris
      slug: paris
      parent: usa/tx
      location_type: city
"""
    report = _apply(text, patch_id="0001-paris")
    assert report.records_created == 1

    loc = Location.objects.get(location_path="usa/tx/paris")
    assert loc.slug == "paris"
    assert loc.name == "Paris"
    assert loc.location_type == "city"
    assert loc.parent is not None
    assert loc.parent.location_path == "usa/tx"
    # Claims back the author-written fields; location_path is system-derived,
    # so it carries no claim.
    keys = set(loc.claims.filter(is_active=True).values_list("field_name", flat=True))
    assert {"slug", "name", "parent", "status"} <= keys
    assert "location_path" not in keys


def test_create_location_at_root():
    text = """
attribution: flip-museum
claims:
  - location.france:
      create: true
      name: France
      slug: france
      location_type: country
"""
    report = _apply(text, patch_id="0001-france")
    assert report.records_created == 1
    loc = Location.objects.get(location_path="france")
    assert loc.parent_id is None
    assert loc.slug == "france"


def test_create_location_path_mismatch_rejected():
    # Reference says usa/tx/paris but parent=usa + slug=paris composes to
    # usa/paris — a disagreement that would create an inconsistent row.
    _country("usa", "USA")
    text = """
attribution: flip-museum
claims:
  - location.usa/tx/paris:
      create: true
      name: Paris
      slug: paris
      parent: usa
"""
    with pytest.raises(PatchError, match="does not match"):
        _apply(text)


def test_create_location_requires_slug():
    _country("usa", "USA")
    text = """
attribution: flip-museum
claims:
  - location.usa/paris:
      create: true
      name: Paris
      parent: usa
"""
    with pytest.raises(PatchError, match="requires 'slug'"):
        _apply(text)


def test_create_location_rejects_authored_location_path():
    _country("usa", "USA")
    text = """
attribution: flip-museum
claims:
  - location.usa/paris:
      create: true
      name: Paris
      slug: paris
      parent: usa
      location_path: usa/paris
"""
    with pytest.raises(PatchError, match="do not set"):
        _apply(text)


def test_missing_reference_without_create_errors():
    text = """
attribution: flip-museum
claims:
  - manufacturer.does-not-exist:
      name: Nope
"""
    with pytest.raises(PatchError, match="no such"):
        _apply(text)


# ── Create + FK reassignment (the stern shape) ─────────────────────


def test_create_and_fk_reassignment(stern_entity, stern):
    text = """
attribution: flip-museum
description: split a firm out
claims:
  - manufacturer.western-products:
      name: Western Products
      create: true
  - corporate-entity.stern-pinball-inc:
      expect: { manufacturer: stern }
      manufacturer: western-products
"""
    report = _apply(text, patch_id="0002-stern")
    assert report.rejected == 0

    new_mfr = Manufacturer.objects.get(slug="western-products")
    stern_entity.refresh_from_db()
    assert stern_entity.manufacturer_id == new_mfr.pk
    # Old parent detached.
    assert not stern.entities.exists()


def test_dry_run_stern_shape_no_spurious_rejection(stern_entity):
    text = """
attribution: flip-museum
claims:
  - manufacturer.western-products:
      name: Western Products
      create: true
  - corporate-entity.stern-pinball-inc:
      expect: { manufacturer: stern }
      manufacturer: western-products
"""
    report = _apply(text, patch_id="0002-stern", dry_run=True)
    # The FK reassignment to a same-plan-created manufacturer must NOT be
    # rejected just because the target doesn't exist yet.
    assert report.rejected == 0
    assert not Manufacturer.objects.filter(slug="western-products").exists()
    assert not IngestRun.objects.filter(patch_id="0002-stern").exists()


def test_relationship_member_created_same_patch_is_rejected(machine_model):
    # Unlike FK fields, relationship members are resolved against the DB
    # eagerly — a member created in the same patch is not supported (it must
    # already exist). See docs/DataPatches.md "Limits".
    text = f"""
attribution: flip-museum
claims:
  - tag.brand-new-tag:
      name: Brand New Tag
      create: true
  - model.{machine_model.slug}:
      tag: [brand-new-tag]
"""
    with pytest.raises(PatchError, match="does not resolve"):
        _apply(text)


# ── Drift guard ────────────────────────────────────────────────────


def test_expect_scalar_match_applies(machine_model):
    text = f"""
attribution: flip-museum
claims:
  - model.{machine_model.slug}:
      expect: {{ year: {machine_model.year} }}
      year: 1990
"""
    _apply(text)
    machine_model.refresh_from_db()
    assert machine_model.year == 1990


def test_expect_scalar_mismatch_errors_before_write(machine_model):
    text = f"""
attribution: flip-museum
claims:
  - model.{machine_model.slug}:
      expect: {{ year: 1234 }}
      year: 1990
"""
    with pytest.raises(PatchError, match="expect year"):
        _apply(text)
    assert not Claim.objects.filter(source__slug="flip-museum").exists()


def test_expect_fk_match_and_mismatch(stern_entity):
    ok = """
attribution: flip-museum
claims:
  - corporate-entity.stern-pinball-inc:
      expect: { manufacturer: stern }
      year_start: 1986
"""
    _apply(ok, patch_id="0001-ok")
    stern_entity.refresh_from_db()
    assert stern_entity.year_start == 1986

    bad = """
attribution: flip-museum
claims:
  - corporate-entity.stern-pinball-inc:
      expect: { manufacturer: williams }
      year_start: 1990
"""
    with pytest.raises(PatchError, match="expect manufacturer"):
        _apply(bad, patch_id="0002-bad")


def test_expect_on_create_errors():
    text = """
attribution: flip-museum
claims:
  - manufacturer.acme-pinball:
      name: Acme
      create: true
      expect: { name: Acme }
"""
    with pytest.raises(PatchError, match="meaningless on a create"):
        _apply(text)


# ── Retract ────────────────────────────────────────────────────────


def test_retract_must_be_a_list():
    with pytest.raises(PatchError, match="'retract' must be a list"):
        load_patch(
            "attribution: flip-museum\nclaims:\n  - model.a:\n      retract: name\n"
        )


def test_retract_fk_falls_through_to_remaining_source(stern, manufacturer):
    # Two sources claim the manufacturer FK; retracting the winning source's
    # claim makes resolution fall through to the remaining source's value.
    catalog = Source.objects.create(
        name="Flipcommons Catalog",
        slug="flipcommons-catalog",
        source_type="editorial",
        priority=300,
    )
    ipdb = Source.objects.create(
        name="IPDB", slug="ipdb", source_type="database", priority=100
    )
    ce = CorporateEntity.objects.create(
        name="Western Products, Inc.",
        slug="western-products-incorporated",
        manufacturer=stern,
    )
    Claim.objects.assert_claim(ce, "name", "Western Products, Inc.", source=catalog)
    Claim.objects.assert_claim(ce, "manufacturer", "williams", source=catalog)
    Claim.objects.assert_claim(ce, "manufacturer", "stern", source=ipdb)

    text = """
attribution: flipcommons-catalog
description: drop our manufacturer claim
claims:
  - corporate-entity.western-products-incorporated:
      retract: [manufacturer]
"""
    report = _apply(text, patch_id="0001-retract")
    assert report.retracted == 1

    ce.refresh_from_db()
    assert ce.manufacturer_id == stern.pk  # fell through to ipdb=stern

    assert not Claim.objects.filter(
        source=catalog, field_name="manufacturer", is_active=True
    ).exists()
    assert Claim.objects.filter(
        source=ipdb, field_name="manufacturer", is_active=True
    ).exists()


def test_retract_sole_required_fk_claim_preserves_value(stern):
    # The safety net: retracting the only claim for a non-nullable FK leaves no
    # active claim, but resolution preserves the current value (the FK is in
    # preserve_when_unclaimed) rather than nulling it — no IntegrityError.
    ipdb = Source.objects.create(
        name="IPDB", slug="ipdb", source_type="database", priority=100
    )
    ce = CorporateEntity.objects.create(
        name="Western Products, Inc.",
        slug="western-products-incorporated",
        manufacturer=stern,
    )
    Claim.objects.assert_claim(ce, "name", "Western Products, Inc.", source=ipdb)
    Claim.objects.assert_claim(ce, "manufacturer", "stern", source=ipdb)

    text = """
attribution: ipdb
claims:
  - corporate-entity.western-products-incorporated:
      retract: [manufacturer]
"""
    report = _apply(text, patch_id="0001-retract-sole")
    assert report.retracted == 1

    ce.refresh_from_db()
    assert ce.manufacturer_id == stern.pk  # value frozen, not nulled
    assert not Claim.objects.filter(field_name="manufacturer", is_active=True).exists()


def test_retract_idempotent_when_claim_absent(stern):
    # An already-gone retract target warns (not errors), so re-running a patch
    # whose claim was already removed is a no-op.
    ipdb = Source.objects.create(
        name="IPDB", slug="ipdb", source_type="database", priority=100
    )
    ce = CorporateEntity.objects.create(
        name="Western Products, Inc.",
        slug="western-products-incorporated",
        manufacturer=stern,
    )
    Claim.objects.assert_claim(ce, "name", "Western Products, Inc.", source=ipdb)

    text = """
attribution: ipdb
claims:
  - corporate-entity.western-products-incorporated:
      retract: [manufacturer]
"""
    report = _apply(text, patch_id="0001-noop")
    assert report.retracted == 0
    assert any("Retract target not found" in w for w in report.warnings)


def test_retract_plus_create_rejected():
    text = """
attribution: flip-museum
claims:
  - manufacturer.acme:
      create: true
      name: Acme
      retract: [name]
"""
    with pytest.raises(PatchError, match="meaningless on a create"):
        _apply(text)


def test_retract_unknown_field_rejected(machine_model):
    text = f"""
attribution: flip-museum
claims:
  - model.{machine_model.slug}:
      retract: [not_a_field]
"""
    with pytest.raises(PatchError, match="cannot retract"):
        _apply(text)


def test_retract_relationship_namespace_rejected(machine_model):
    # Relationship retract is deferred; a namespace key (`tag`) is rejected
    # with a relationship-specific message (distinct from an unknown field).
    text = f"""
attribution: flip-museum
claims:
  - model.{machine_model.slug}:
      retract: [tag]
"""
    with pytest.raises(PatchError, match="relationship retract is unsupported"):
        _apply(text)


def test_retract_one_field_assert_another_in_same_entry(stern):
    # An entry may retract one field and assert a different one.
    catalog = Source.objects.create(
        name="Flipcommons Catalog",
        slug="flipcommons-catalog",
        source_type="editorial",
        priority=300,
    )
    ipdb = Source.objects.create(
        name="IPDB", slug="ipdb", source_type="database", priority=100
    )
    ce = CorporateEntity.objects.create(
        name="Western Products, Inc.",
        slug="western-products-incorporated",
        manufacturer=stern,
    )
    Claim.objects.assert_claim(ce, "name", "Western Products, Inc.", source=ipdb)
    Claim.objects.assert_claim(ce, "manufacturer", "stern", source=ipdb)
    Claim.objects.assert_claim(ce, "manufacturer", "stern", source=catalog)

    text = """
attribution: ipdb
claims:
  - corporate-entity.western-products-incorporated:
      retract: [manufacturer]
      year_start: 1977
"""
    report = _apply(text, patch_id="0001-mix")
    assert report.retracted == 1
    assert report.asserted == 1

    ce.refresh_from_db()
    assert ce.year_start == 1977
    assert ce.manufacturer_id == stern.pk  # catalog claim keeps the FK
    assert not Claim.objects.filter(
        source=ipdb, field_name="manufacturer", is_active=True
    ).exists()


def test_retract_and_assert_same_field_rejected(stern):
    ipdb = Source.objects.create(
        name="IPDB", slug="ipdb", source_type="database", priority=100
    )
    ce = CorporateEntity.objects.create(
        name="Western Products, Inc.",
        slug="western-products-incorporated",
        manufacturer=stern,
    )
    Claim.objects.assert_claim(ce, "name", "Western Products, Inc.", source=ipdb)
    text = """
attribution: ipdb
claims:
  - corporate-entity.western-products-incorporated:
      retract: [manufacturer]
      manufacturer: stern
"""
    with pytest.raises(PatchError, match="cannot both retract and assert"):
        _apply(text)


def test_retract_and_assert_same_field_across_entries_rejected(stern):
    # The conflict is rejected even when the retract and the assert live in
    # separate entries for the same entity — the retract would otherwise be a
    # silent no-op (the assert always wins).
    ipdb = Source.objects.create(
        name="IPDB", slug="ipdb", source_type="database", priority=100
    )
    ce = CorporateEntity.objects.create(
        name="Western Products, Inc.",
        slug="western-products-incorporated",
        manufacturer=stern,
    )
    Claim.objects.assert_claim(ce, "name", "Western Products, Inc.", source=ipdb)
    text = """
attribution: ipdb
claims:
  - corporate-entity.western-products-incorporated:
      retract: [manufacturer]
  - corporate-entity.western-products-incorporated:
      manufacturer: stern
"""
    with pytest.raises(PatchError, match="cannot both retract and assert"):
        _apply(text)


# ── Remove relationship member (exists=false supersede) ────────────


@pytest.fixture
def bally_wulff(db):
    """A CorporateEntity whose sole location is Germany, claimed by flip-museum.

    Mirrors the real case: a coarse pindata-derived location we refine to a more
    specific child (Berlin). The membership claim is attributed to flip-museum so
    a patch from the same source supersedes it; Berlin is seeded as a child of
    Germany, ready to assert.
    """
    museum = Source.objects.get(slug="flip-museum")
    germany = Location.objects.create(
        location_path="germany",
        slug="germany",
        name="Germany",
        location_type="country",
    )
    Location.objects.create(
        location_path="germany/berlin",
        slug="berlin",
        name="Berlin",
        location_type="city",
        parent=germany,
    )
    mfr = Manufacturer.objects.create(name="Bally Wulff", slug="bally-wulff-mfr")
    ce = CorporateEntity.objects.create(
        name="Bally Wulff", slug="bally-wulff", manufacturer=mfr
    )
    Claim.objects.assert_claim(ce, "name", "Bally Wulff", source=museum)
    claim_key, value = build_relationship_claim("location", {"location": germany.pk})
    Claim.objects.assert_claim(
        ce, "location", value, source=museum, claim_key=claim_key
    )
    resolve_all_corporate_entity_locations(subject_ids={ce.pk})
    return ce


def _location_claim(slug: str) -> Claim:
    """The active 'location' claim for the member Location with *slug*."""
    loc = Location.objects.get(slug=slug)
    claim_key, _ = build_relationship_claim("location", {"location": loc.pk})
    return Claim.objects.get(claim_key=claim_key, field_name="location", is_active=True)


def _ce_location_paths(ce: CorporateEntity) -> set[str]:
    return set(
        CorporateEntityLocation.objects.filter(corporate_entity=ce).values_list(
            "location__location_path", flat=True
        )
    )


def test_remove_member_and_assert_more_specific(bally_wulff):
    # The Germany→Berlin refinement: supersede the Germany membership with an
    # exists=false tombstone and assert Berlin. The resolved set ends as Berlin.
    text = """
attribution: flip-museum
claims:
  - corporate-entity.bally-wulff:
      location: [germany/berlin]
      remove: { location: [germany] }
      note: 'Bally Wulff is headquartered in Berlin; Germany was the coarser value.'
"""
    report = _apply(text, patch_id="0001-berlin")
    assert report.rejected == 0

    assert _ce_location_paths(bally_wulff) == {"germany/berlin"}
    # Germany's membership is superseded by an *active* exists=false claim (not
    # deactivated): the claim stays, resolving to absent.
    assert _location_claim("germany").value["exists"] is False
    assert _location_claim("berlin").value["exists"] is True
    # One entry → one shared changeset carrying the note.
    berlin_changeset = _location_claim("berlin").changeset
    assert berlin_changeset is not None
    assert berlin_changeset.note.startswith("Bally Wulff")


def test_remove_only_member_empties_relationship(bally_wulff):
    # A remove with no accompanying assert is a valid, provenance-bearing entry:
    # the exists=false tombstone is the carrier.
    text = """
attribution: flip-museum
claims:
  - corporate-entity.bally-wulff:
      remove: { location: [germany] }
      note: 'Location unknown; the Germany value was unsupported.'
"""
    report = _apply(text, patch_id="0001-drop")
    assert report.rejected == 0
    assert _ce_location_paths(bally_wulff) == set()
    assert _location_claim("germany").value["exists"] is False


def test_remove_cite_and_note_ride_the_tombstone(bally_wulff):
    text = """
attribution: flip-museum
claims:
  - corporate-entity.bally-wulff:
      remove: { location: [germany] }
      note: 'flip-museum says "headquartered in Berlin".'
      cite: https://example.org/bally-wulff
sources:
  - name: Example
    source_type: web
    links:
      - { url: "https://example.org/", label: Example, link_type: homepage }
"""
    _apply(text, patch_id="0001-cite")
    tombstone = _location_claim("germany")
    assert tombstone.value["exists"] is False
    assert tombstone.changeset is not None
    assert tombstone.changeset.note == 'flip-museum says "headquartered in Berlin".'
    assert CitationInstance.objects.filter(claim=tombstone).exists()


def test_remove_must_be_a_mapping():
    text = (
        "attribution: flip-museum\nclaims:\n"
        "  - corporate-entity.a:\n      remove: [location]\n"
    )
    with pytest.raises(PatchError, match="'remove' must be a mapping"):
        load_patch(text)


def test_remove_scalar_field_rejected(bally_wulff):
    # A scalar/FK field isn't a relationship namespace — point the author at
    # retract: instead.
    text = """
attribution: flip-museum
claims:
  - corporate-entity.bally-wulff:
      remove: { manufacturer: [williams] }
"""
    with pytest.raises(PatchError, match="not a relationship namespace"):
        _apply(text)


def test_remove_relationship_not_valid_on_subject(bally_wulff):
    # 'theme' is a relationship namespace, but not on CorporateEntity.
    text = """
attribution: flip-museum
claims:
  - corporate-entity.bally-wulff:
      remove: { theme: [medieval] }
"""
    with pytest.raises(PatchError, match="is not valid on"):
        _apply(text)


def test_remove_unknown_member_rejected(bally_wulff):
    text = """
attribution: flip-museum
claims:
  - corporate-entity.bally-wulff:
      remove: { location: [atlantis] }
"""
    with pytest.raises(PatchError, match="does not resolve"):
        _apply(text)


def test_remove_noop_when_source_lacks_claim(bally_wulff):
    # flip-museum never claimed Berlin membership, so removing it writes no
    # tombstone — a warning, not an error, so re-running a patch stays safe.
    text = """
attribution: flip-museum
claims:
  - corporate-entity.bally-wulff:
      remove: { location: [germany/berlin] }
"""
    report = _apply(text, patch_id="0001-noop")
    assert report.rejected == 0
    assert any("no-op" in w for w in report.warnings)
    # Germany membership untouched; no exists=false claim for Berlin.
    assert _ce_location_paths(bally_wulff) == {"germany"}
    berlin = Location.objects.get(slug="berlin")
    bk, _ = build_relationship_claim("location", {"location": berlin.pk})
    assert not Claim.objects.filter(claim_key=bk).exists()


def test_remove_noop_with_note_rejected(bally_wulff):
    # A no-op removal emits no tombstone, so a note: on a remove-only entry would
    # have nothing to attach to and would silently vanish — reject it loudly
    # instead (same rule cite: already follows).
    text = """
attribution: flip-museum
claims:
  - corporate-entity.bally-wulff:
      remove: { location: [germany/berlin] }
      note: 'flip-museum says "not in Berlin".'
"""
    with pytest.raises(PatchError, match="note has nothing to attach to"):
        _apply(text, patch_id="0001-noop-note")


def test_remove_and_assert_same_member_rejected(bally_wulff):
    # Asserting a member present and removing it in one patch would write the
    # same claim_key twice with opposite exists — reject the contradiction.
    text = """
attribution: flip-museum
claims:
  - corporate-entity.bally-wulff:
      location: [germany]
      remove: { location: [germany] }
"""
    with pytest.raises(PatchError, match="cannot both assert and remove"):
        _apply(text)


def test_remove_and_assert_same_member_rejected_when_unclaimed(bally_wulff):
    # The contradiction is an authoring error knowable from the patch text, so it
    # must be rejected regardless of DB state — even when the source does NOT
    # currently claim the member (so the removal is a no-op). flip-museum claims
    # germany, not germany/berlin, so the remove here is a no-op.
    text = """
attribution: flip-museum
claims:
  - corporate-entity.bally-wulff:
      location: [germany/berlin]
      remove: { location: [germany/berlin] }
"""
    with pytest.raises(PatchError, match="cannot both assert and remove"):
        _apply(text)


def test_remove_plus_create_rejected():
    text = """
attribution: flip-museum
claims:
  - corporate-entity.new-firm:
      name: New Firm
      create: true
      remove: { location: [germany] }
"""
    with pytest.raises(PatchError, match="'remove' is meaningless on a create"):
        _apply(text)


def test_remove_plus_delete_rejected(bally_wulff):
    text = """
attribution: flip-museum
claims:
  - corporate-entity.bally-wulff:
      delete: true
      remove: { location: [germany] }
"""
    with pytest.raises(
        PatchError, match="'remove' and 'delete' are mutually exclusive"
    ):
        _apply(text)


# ── Delete ─────────────────────────────────────────────────────────


def test_delete_marks_status_deleted(stern_entity):
    # stern_entity has no active referrer, so the delete proceeds and resolves
    # status=deleted onto the entity.
    text = """
attribution: flip-museum
claims:
  - corporate-entity.stern-pinball-inc:
      delete: true
"""
    report = _apply(text, patch_id="0001-del")
    assert report.rejected == 0
    assert report.asserted == 1
    stern_entity.refresh_from_db()
    assert stern_entity.status == "deleted"
    # The entity drops out of the active manager.
    assert not CorporateEntity.objects.active().filter(pk=stern_entity.pk).exists()


def test_delete_blocked_by_active_referrer(machine_model):
    # machine_model.corporate_entity → williams_entity (a PROTECT FK). The
    # active machine blocks the CE delete; the blocker is reported before any
    # write, naming the referrer and the relation.
    text = """
attribution: flip-museum
claims:
  - corporate-entity.williams-electronics:
      delete: true
"""
    with pytest.raises(PatchError, match="cannot delete.*still referenced"):
        _apply(text, patch_id="0001-del")
    assert not Claim.objects.filter(
        source__slug="flip-museum", field_name="status"
    ).exists()


def test_delete_blocked_caught_in_dry_run(machine_model):
    # The blocker check is a build-phase DB read, so --dry-run surfaces it too.
    text = """
attribution: flip-museum
claims:
  - corporate-entity.williams-electronics:
      delete: true
"""
    with pytest.raises(PatchError, match="cannot delete"):
        _apply(text, patch_id="0001-del", dry_run=True)


def test_reassign_in_earlier_patch_then_delete(machine_model, stern_entity):
    # The real workflow: the referrer is reassigned away first (its own patch,
    # applied and resolved), which clears the blocker for a later delete patch.
    reassign = f"""
attribution: flip-museum
claims:
  - model.{machine_model.slug}:
      expect: {{ corporate_entity: williams-electronics }}
      corporate_entity: stern-pinball-inc
"""
    _apply(reassign, patch_id="0001-reassign")
    machine_model.refresh_from_db()
    assert machine_model.corporate_entity_id == stern_entity.pk

    delete = """
attribution: flip-museum
claims:
  - corporate-entity.williams-electronics:
      delete: true
"""
    report = _apply(delete, patch_id="0002-delete")
    assert report.rejected == 0
    williams = CorporateEntity.objects.get(slug="williams-electronics")
    assert williams.status == "deleted"


def test_delete_is_idempotent(stern_entity):
    text = """
attribution: flip-museum
claims:
  - corporate-entity.stern-pinball-inc:
      delete: true
"""
    r1 = _apply(text, patch_id="0001-del")
    assert r1.asserted == 1
    # Re-running the same delete (different patch_id) is a clean no-op — the
    # status=deleted claim already exists and diffs as unchanged.
    r2 = _apply(text, patch_id="0002-del")
    assert r2.asserted == 0
    assert r2.unchanged == 1
    stern_entity.refresh_from_db()
    assert stern_entity.status == "deleted"


def test_delete_with_expect_guard(stern_entity):
    # A mismatched expect: fails loudly before the delete writes anything.
    bad = """
attribution: flip-museum
claims:
  - corporate-entity.stern-pinball-inc:
      expect: { manufacturer: williams }
      delete: true
"""
    with pytest.raises(PatchError, match="expect manufacturer"):
        _apply(bad, patch_id="0001-bad")
    stern_entity.refresh_from_db()
    assert stern_entity.status != "deleted"

    ok = """
attribution: flip-museum
claims:
  - corporate-entity.stern-pinball-inc:
      expect: { manufacturer: stern }
      delete: true
"""
    _apply(ok, patch_id="0002-ok")
    stern_entity.refresh_from_db()
    assert stern_entity.status == "deleted"


def test_delete_nonexistent_rejected():
    text = """
attribution: flip-museum
claims:
  - corporate-entity.no-such-entity:
      delete: true
"""
    with pytest.raises(PatchError, match="no such corporate-entity to delete"):
        _apply(text)


def test_delete_with_create_rejected():
    text = """
attribution: flip-museum
claims:
  - corporate-entity.acme:
      create: true
      delete: true
"""
    with pytest.raises(PatchError, match="mutually exclusive"):
        _apply(text)


def test_delete_with_retract_rejected(stern_entity):
    text = """
attribution: flip-museum
claims:
  - corporate-entity.stern-pinball-inc:
      delete: true
      retract: [year_start]
"""
    with pytest.raises(PatchError, match="mutually exclusive"):
        _apply(text)


def test_delete_with_field_assertion_rejected(stern_entity):
    # A delete entry carries no field assertions — reassign references in a
    # separate entry/patch, before the delete.
    text = """
attribution: flip-museum
claims:
  - corporate-entity.stern-pinball-inc:
      delete: true
      year_start: 1999
"""
    with pytest.raises(PatchError, match="takes no field assertions"):
        _apply(text)


def test_assert_status_field_rejected(stern_entity):
    # 'status' is lifecycle state. Asserting it as a raw claim field would
    # bypass the delete planner (no blocker check, no cascade) — reject it and
    # point the author at the directive.
    text = """
attribution: flip-museum
claims:
  - corporate-entity.stern-pinball-inc:
      status: deleted
"""
    with pytest.raises(PatchError, match="'status' is lifecycle"):
        _apply(text)
    stern_entity.refresh_from_db()
    assert stern_entity.status != "deleted"


def test_assert_status_field_does_not_bypass_blocker(machine_model):
    # The back door must not let a raw status=deleted slip past the active
    # PROTECT referrer that delete: true correctly rejects.
    text = """
attribution: flip-museum
claims:
  - corporate-entity.williams-electronics:
      status: deleted
"""
    with pytest.raises(PatchError, match="'status' is lifecycle"):
        _apply(text)
    assert not Claim.objects.filter(
        source__slug="flip-museum", field_name="status"
    ).exists()


def test_delete_cascade_child_same_entity_provenance_guard(machine_model):
    # Deleting a Title cascades status=deleted onto its MachineModels. A
    # separate entry that puts note/cite on a cascaded child collides in that
    # child's single ChangeSet — the same-entity guard must catch it even
    # though the child was only reached via the cascade.
    text = """
attribution: flip-museum
claims:
  - title.medieval-madness-title:
      delete: true
  - model.medieval-madness:
      note: 'edit on a machine that the cascade is deleting'
      year: 1998
"""
    with pytest.raises(PatchError, match="multiple entries target this entity"):
        _apply(text)


def test_delete_must_be_boolean():
    with pytest.raises(PatchError, match="'delete' must be a boolean"):
        load_patch(
            "attribution: flip-museum\nclaims:\n"
            "  - corporate-entity.x:\n      delete: yes\n"
        )


def test_delete_note_and_cite_attach_to_status_claim(stern_entity):
    text = """
attribution: flip-museum
claims:
  - corporate-entity.stern-pinball-inc:
      delete: true
      note: 'flip-museum says "this firm never existed".'
      cite: https://example.org/proof
sources:
  - name: Example
    source_type: web
    links:
      - { url: "https://example.org/", label: Example, link_type: homepage }
"""
    _apply(text, patch_id="0001-del")
    status_claim = Claim.objects.get(
        source__slug="flip-museum", field_name="status", is_active=True
    )
    assert status_claim.value == "deleted"
    changeset = status_claim.changeset
    assert changeset is not None
    assert changeset.note == 'flip-museum says "this firm never existed".'
    assert CitationInstance.objects.filter(claim=status_claim).exists()


# ── Idempotency (engine-level no-op) ───────────────────────────────


def test_reassert_same_claim_is_noop(machine_model):
    text = f"""
attribution: flip-museum
claims:
  - model.{machine_model.slug}:
      year: 1990
"""
    r1 = _apply(text, patch_id="0001-a")
    assert r1.asserted == 1
    r2 = _apply(text, patch_id="0001-b")
    assert r2.asserted == 0
    assert r2.unchanged == 1


# ── One IngestRun per patch, one ChangeSet per entity ──────────────


def test_one_ingestrun_one_changeset(machine_model):
    text = f"""
attribution: flip-museum
claims:
  - model.{machine_model.slug}:
      year: 1990
"""
    _apply(text, patch_id="0001-x")
    run = IngestRun.objects.get(patch_id="0001-x")
    assert run.status == IngestRun.Status.SUCCESS
    assert run.note == ""  # no description in this patch
    assert ChangeSet.objects.filter(ingest_run=run).count() == 1


# ── DB constraints ─────────────────────────────────────────────────


def _src() -> Source:
    return Source.objects.get(slug="flip-museum")


def test_uppercase_patch_id_rejected():
    # The DB check is portable (lowercase via Lower(), not regex); the exact
    # NNNN-slug format is enforced by the command's pre-flight.
    with pytest.raises(IntegrityError):
        IngestRun.objects.create(
            source=_src(), patch_id="0001-BAD", input_fingerprint="a" * 64
        )


def test_empty_patch_id_rejected():
    with pytest.raises(IntegrityError):
        IngestRun.objects.create(source=_src(), patch_id="", input_fingerprint="a" * 64)


def test_normal_ingest_patch_id_null_unconstrained():
    # No patch_id → the patch checks don't apply; any fingerprint is fine.
    run = IngestRun.objects.create(source=_src(), input_fingerprint="anything")
    assert run.patch_id is None


def test_patch_applied_once():
    now = timezone.now()
    IngestRun.objects.create(
        source=_src(),
        patch_id="0001-x",
        input_fingerprint="a" * 64,
        status=IngestRun.Status.SUCCESS,
        finished_at=now,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        IngestRun.objects.create(
            source=_src(),
            patch_id="0001-x",
            input_fingerprint="b" * 64,
            status=IngestRun.Status.SUCCESS,
            finished_at=now,
        )


# ── Command: discovery, pre-flight, ledger, immutability ───────────


def _write(dir_path: Path, name: str, text: str) -> None:
    (dir_path / name).write_text(text, encoding="utf-8")


def test_command_applies_and_skips_on_rerun(tmp_path, machine_model):
    text = f"""
attribution: flip-museum
description: tag it
claims:
  - model.{machine_model.slug}:
      year: 1990
"""
    _write(tmp_path, "0001-year.yaml", text)

    call_command("ingest_patches", "--patches-dir", str(tmp_path))
    assert (
        IngestRun.objects.filter(
            patch_id="0001-year", status=IngestRun.Status.SUCCESS
        ).count()
        == 1
    )

    # Re-run → ledger hit, no new success run.
    call_command("ingest_patches", "--patches-dir", str(tmp_path))
    assert (
        IngestRun.objects.filter(
            patch_id="0001-year", status=IngestRun.Status.SUCCESS
        ).count()
        == 1
    )


def test_command_immutability_semantic_change(tmp_path, machine_model):
    p = tmp_path / "0001-year.yaml"
    p.write_text(
        f"attribution: flip-museum\nclaims:\n  - model.{machine_model.slug}:\n      year: 1990\n",
        encoding="utf-8",
    )
    call_command("ingest_patches", "--patches-dir", str(tmp_path))

    # Semantic change to an applied patch → hard error.
    p.write_text(
        f"attribution: flip-museum\nclaims:\n  - model.{machine_model.slug}:\n      year: 1991\n",
        encoding="utf-8",
    )
    with pytest.raises(CommandError, match="immutable"):
        call_command("ingest_patches", "--patches-dir", str(tmp_path))


def test_command_immutability_cosmetic_reformat_skips(tmp_path, machine_model):
    p = tmp_path / "0001-year.yaml"
    p.write_text(
        f"attribution: flip-museum\nclaims:\n  - model.{machine_model.slug}:\n      year: 1990\n",
        encoding="utf-8",
    )
    call_command("ingest_patches", "--patches-dir", str(tmp_path))

    # Cosmetic reformat (added comment + blank lines + spacing) → still skips.
    p.write_text(
        f"# a comment\nattribution:   flip-museum\n\nclaims:\n\n  - model.{machine_model.slug}:\n      year: 1990\n",
        encoding="utf-8",
    )
    call_command("ingest_patches", "--patches-dir", str(tmp_path))
    assert (
        IngestRun.objects.filter(
            patch_id="0001-year", status=IngestRun.Status.SUCCESS
        ).count()
        == 1
    )


def test_command_preflight_bad_filename(tmp_path):
    _write(tmp_path, "not-numbered.yaml", "attribution: flip-museum\nclaims: []\n")
    with pytest.raises(CommandError, match="NNNN-slug"):
        call_command("ingest_patches", "--patches-dir", str(tmp_path))


def test_command_preflight_duplicate_prefix(tmp_path):
    _write(tmp_path, "0001-a.yaml", "attribution: flip-museum\nclaims: []\n")
    _write(tmp_path, "0001-b.yaml", "attribution: flip-museum\nclaims: []\n")
    with pytest.raises(CommandError, match="Duplicate patch number"):
        call_command("ingest_patches", "--patches-dir", str(tmp_path))


def test_command_missing_attribution_source(tmp_path, machine_model):
    _write(
        tmp_path,
        "0001-x.yaml",
        f"attribution: no-such-source\nclaims:\n  - model.{machine_model.slug}:\n      year: 1990\n",
    )
    with pytest.raises(CommandError, match="does not exist"):
        call_command("ingest_patches", "--patches-dir", str(tmp_path))


def test_command_stops_at_first_failure(tmp_path, machine_model):
    # 0001 applies; 0002 fails (missing ref); 0003 must not apply.
    _write(
        tmp_path,
        "0001-ok.yaml",
        f"attribution: flip-museum\nclaims:\n  - model.{machine_model.slug}:\n      year: 1990\n",
    )
    _write(
        tmp_path,
        "0002-bad.yaml",
        "attribution: flip-museum\nclaims:\n  - manufacturer.nope:\n      name: Nope\n",
    )
    _write(
        tmp_path,
        "0003-later.yaml",
        f"attribution: flip-museum\nclaims:\n  - model.{machine_model.slug}:\n      year: 1992\n",
    )
    with pytest.raises(CommandError):
        call_command("ingest_patches", "--patches-dir", str(tmp_path))

    assert IngestRun.objects.filter(
        patch_id="0001-ok", status=IngestRun.Status.SUCCESS
    ).exists()
    assert not IngestRun.objects.filter(
        patch_id="0003-later", status=IngestRun.Status.SUCCESS
    ).exists()


def test_command_invalid_claim_value_reported(tmp_path, stern_entity):
    # An out-of-range value is a normal authoring error: apply_plan raises
    # ValidationError, which must surface as a clean failure, not a traceback.
    _write(
        tmp_path,
        "0001-bad.yaml",
        "attribution: flip-museum\n"
        "claims:\n"
        "  - corporate-entity.stern-pinball-inc:\n"
        "      year_start: 5000\n",
    )
    with pytest.raises(CommandError):
        call_command("ingest_patches", "--patches-dir", str(tmp_path))
    # Failed run recorded (for audit), no successful application.
    assert not IngestRun.objects.filter(
        patch_id="0001-bad", status=IngestRun.Status.SUCCESS
    ).exists()


# ── Citation sources (the `sources:` block) ────────────────────────


_WIKIPEDIA = """
attribution: flip-museum
sources:
  - name: Wikipedia
    source_type: web
    description: Free collaborative encyclopedia.
    links:
      - { url: "https://en.wikipedia.org/", label: Wikipedia, link_type: homepage }
"""


# -- Parsing / shape --


def test_sources_block_parsed():
    doc = load_patch(_WIKIPEDIA)
    assert len(doc.sources) == 1
    assert doc.sources[0]["name"] == "Wikipedia"
    assert doc.claims == []


def test_sources_only_patch_is_valid_and_applies():
    report = _apply(_WIKIPEDIA, patch_id="0001-wiki")
    assert report.sources_created == 1
    assert report.source_links_created == 1
    src = CitationSource.objects.get(name="Wikipedia", source_type="web")
    assert src.parent_id is None
    assert CitationSourceLink.objects.filter(
        citation_source=src, url="https://en.wikipedia.org/", link_type="homepage"
    ).exists()


def test_empty_patch_rejected():
    with pytest.raises(PatchError, match="non-empty"):
        load_patch("attribution: flip-museum\nclaims: []\n")


def test_sources_missing_name_rejected():
    with pytest.raises(PatchError, match="'name' is required"):
        load_patch("attribution: flip-museum\nsources:\n  - source_type: web\n")


def test_sources_unknown_key_rejected():
    text = (
        "attribution: flip-museum\n"
        "sources:\n"
        "  - name: X\n"
        "    source_type: web\n"
        "    descriptoin: typo\n"
    )
    with pytest.raises(PatchError, match="unknown key"):
        load_patch(text)


def test_sources_children_rejected():
    text = (
        "attribution: flip-museum\n"
        "sources:\n"
        "  - name: X\n"
        "    source_type: web\n"
        "    children: []\n"
    )
    with pytest.raises(PatchError, match="children"):
        load_patch(text)


def test_sources_link_missing_url_rejected():
    text = (
        "attribution: flip-museum\n"
        "sources:\n"
        "  - name: X\n"
        "    source_type: web\n"
        "    links:\n"
        "      - { link_type: homepage }\n"
    )
    with pytest.raises(PatchError, match="'url' is required"):
        load_patch(text)


# -- Read-phase semantic validation (caught at build/dry-run) --


def _bad_source(node_body: str) -> str:
    return f"attribution: flip-museum\nsources:\n  - {node_body}\n"


@pytest.mark.parametrize(
    ("node_body", "match"),
    [
        ("name: X\n    source_type: blog", "source_type"),
        ("name: X\n    source_type: web\n    year: 9999", "year"),
        (
            "name: X\n    source_type: web\n"
            "    links:\n      - { url: not-a-url, link_type: homepage }",
            "url",
        ),
        (
            "name: X\n    source_type: web\n"
            "    links:\n      - { url: 'https://a.test/', link_type: bogus }",
            "link_type",
        ),
    ],
)
def test_sources_semantic_invalidity_rejected(node_body, match):
    with pytest.raises(PatchError, match=match):
        _apply(_bad_source(node_body), patch_id="0001-bad-src")


def test_sources_duplicate_declared_link_url_rejected():
    text = (
        "attribution: flip-museum\n"
        "sources:\n"
        "  - name: X\n"
        "    source_type: web\n"
        "    links:\n"
        "      - { url: 'https://a.test/', link_type: homepage }\n"
        "      - { url: 'https://a.test/', link_type: reference }\n"
    )
    with pytest.raises(PatchError, match="duplicate declared link"):
        _apply(text, patch_id="0001-dup-link")


def test_sources_semantic_invalidity_caught_at_dry_run():
    # The whole point of read-phase validation: a bad value fails before any
    # write, so --dry-run surfaces it on localhost before shipping.
    with pytest.raises(PatchError, match="source_type"):
        _apply(_bad_source("name: X\n    source_type: blog"), dry_run=True)


# -- Apply behaviour: additive get-or-create --


_MULTI_LINK = """
attribution: flip-museum
sources:
  - name: Wikipedia
    source_type: web
    links:
      - { url: "https://en.wikipedia.org/", label: Wikipedia, link_type: homepage }
      - { url: "https://de.wikipedia.org/", label: "Wikipedia (Deutsch)", link_type: homepage }
"""


def test_sources_multi_link_node_creates_all_links():
    report = _apply(_MULTI_LINK, patch_id="0001-multi")
    assert report.sources_created == 1
    assert report.source_links_created == 2
    src = CitationSource.objects.get(name="Wikipedia", source_type="web")
    urls = set(src.links.values_list("url", flat=True))
    assert urls == {"https://en.wikipedia.org/", "https://de.wikipedia.org/"}


def test_sources_reapply_identical_is_noop():
    _apply(_WIKIPEDIA, patch_id="0001-a")
    report = _apply(_WIKIPEDIA, patch_id="0001-b")
    assert report.sources_created == 0
    assert report.sources_skipped == 1
    assert report.source_links_created == 0
    assert CitationSource.objects.filter(name="Wikipedia").count() == 1


def test_sources_preexisting_user_source_left_untouched():
    # A user-created collision must never fail or be overwritten.
    user = CitationSource.objects.create(
        name="Wikipedia", source_type="web", description="user wrote this"
    )
    CitationSourceLink.objects.create(
        citation_source=user,
        url="https://en.wikipedia.org/",
        label="Wikipedia",
        link_type="homepage",
    )
    report = _apply(_WIKIPEDIA, patch_id="0001-collide")
    assert report.sources_created == 0
    assert report.sources_skipped == 1
    user.refresh_from_db()
    assert user.description == "user wrote this"  # patch did not overwrite
    assert any("differ" in w for w in report.warnings)


def test_sources_missing_link_backfilled_additively():
    # A bare existing root gets its declared homepage link added (additive).
    CitationSource.objects.create(name="Wikipedia", source_type="web")
    report = _apply(_WIKIPEDIA, patch_id="0001-backfill")
    assert report.sources_created == 0
    assert report.source_links_created == 1
    src = CitationSource.objects.get(name="Wikipedia")
    assert src.links.filter(url="https://en.wikipedia.org/").exists()


def test_sources_divergent_existing_link_left_and_warned():
    src = CitationSource.objects.create(name="Wikipedia", source_type="web")
    CitationSourceLink.objects.create(
        citation_source=src,
        url="https://en.wikipedia.org/",
        label="Different label",
        link_type="reference",
    )
    report = _apply(_WIKIPEDIA, patch_id="0001-link-diff")
    assert report.source_links_created == 0
    link = src.links.get(url="https://en.wikipedia.org/")
    assert link.label == "Different label"  # left as-is
    assert link.link_type == "reference"
    assert any("different type/label" in w for w in report.warnings)


def test_sources_ambiguous_match_uses_first_and_warns():
    CitationSource.objects.create(name="Wikipedia", source_type="web")
    CitationSource.objects.create(name="Wikipedia", source_type="web")
    report = _apply(_WIKIPEDIA, patch_id="0001-ambig")
    assert report.sources_created == 0
    assert any("matched 2 rows" in w for w in report.warnings)
    assert CitationSource.objects.filter(name="Wikipedia").count() == 2  # no new row


def test_sources_same_named_child_does_not_shadow_root():
    # A child sharing (name, source_type) with the declared root must NOT be
    # adopted: the patch creates the parentless root so later cites can nest
    # (recognize_url only sees homepage links on parentless sources).
    farm = CitationSource.objects.create(name="Wiki Farm", source_type="web")
    child = CitationSource.objects.create(
        name="Wikipedia", source_type="web", parent=farm
    )
    report = _apply(_WIKIPEDIA, patch_id="0001-no-shadow")
    assert report.sources_created == 1
    root = CitationSource.objects.get(
        name="Wikipedia", source_type="web", parent__isnull=True
    )
    assert root.pk != child.pk
    assert root.links.filter(url="https://en.wikipedia.org/").exists()
    assert not child.links.exists()  # child left untouched


def test_sources_existing_row_passes_read_phase_validation():
    # Guards the validate_unique=False / exclude=citation_source exclusions:
    # a node matching an existing row + an in-memory link must NOT false-reject.
    src = CitationSource.objects.create(name="Wikipedia", source_type="web")
    CitationSourceLink.objects.create(
        citation_source=src,
        url="https://en.wikipedia.org/",
        label="Wikipedia",
        link_type="homepage",
    )
    report = _apply(_WIKIPEDIA, patch_id="0001-revalidate")
    assert report.sources_skipped == 1  # validated + no-op, no PatchError


# -- Anti-wedge: a sources root makes a later cite resolve --


def test_sources_root_then_cite_nests_no_wedge(machine_model):
    # The headline scenario: create the Wikipedia root, then cite a wikipedia.org
    # page in the same patch. The hook runs first, so the cite recognizes the
    # domain and nests under the root instead of raising.
    text = f"""
attribution: flip-museum
sources:
  - name: Wikipedia
    source_type: web
    links:
      - {{ url: "https://en.wikipedia.org/", label: Wikipedia, link_type: homepage }}
claims:
  - model.{machine_model.slug}:
      year: 1990
      cite: https://en.wikipedia.org/wiki/Pinball
"""
    report = _apply(text, patch_id="0001-root-cite")
    assert report.rejected == 0
    root = CitationSource.objects.get(name="Wikipedia", source_type="web")
    inst = CitationInstance.objects.get()
    assert inst.citation_source.parent_id == root.pk


# -- Audit counters --


def test_sources_only_run_audit_not_zero():
    _apply(_WIKIPEDIA, patch_id="0001-audit")
    run = IngestRun.objects.get(patch_id="0001-audit")
    assert run.status == IngestRun.Status.SUCCESS
    assert run.citation_sources_created == 1
    assert run.citation_source_links_created == 1


def test_link_only_backfill_audit_not_zero():
    CitationSource.objects.create(name="Wikipedia", source_type="web")
    _apply(_WIKIPEDIA, patch_id="0001-link-audit")
    run = IngestRun.objects.get(patch_id="0001-link-audit")
    assert run.status == IngestRun.Status.SUCCESS
    assert run.citation_sources_created == 0
    assert run.citation_source_links_created == 1


def test_command_reports_citation_sources(tmp_path):
    _write(tmp_path, "0001-wiki.yaml", _WIKIPEDIA)
    out = StringIO()
    call_command("ingest_patches", "--patches-dir", str(tmp_path), stdout=out)
    assert "citation sources: 1 created, 1 links added" in out.getvalue()
    assert CitationSource.objects.filter(name="Wikipedia").exists()
