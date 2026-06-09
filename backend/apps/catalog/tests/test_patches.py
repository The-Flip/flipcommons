"""Tests for the data-patch adapter and the ingest_patches command."""

from __future__ import annotations

from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.catalog.ingestion.apply import RunReport, apply_plan
from apps.catalog.ingestion.patches import (
    PatchError,
    build_plan,
    fingerprint,
    load_patch,
    parse_patch_text,
)
from apps.catalog.models import CorporateEntity, Location, Manufacturer, Tag
from apps.provenance.models import ChangeSet, Claim, IngestRun, Source

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
