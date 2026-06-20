"""Tests for the data-patch adapter and the ingest_patches command."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.catalog.models import (
    CorporateEntity,
    CorporateEntityLocation,
    Credit,
    CreditRole,
    GameplayFeature,
    Location,
    MachineModel,
    MachineModelGameplayFeature,
    Manufacturer,
    Person,
    Series,
    Tag,
    Title,
)
from apps.catalog.resolve import resolve_all_corporate_entity_locations
from apps.citation.models import CitationSource, CitationSourceLink
from apps.claim_ingest.apply import apply_plan
from apps.claim_ingest.patches import (
    EditEntry,
    PatchError,
    build_plan,
    fingerprint,
    load_patch,
    parse_patch_text,
)
from apps.claim_ingest.patches.emit import (
    _FkMemberSpec,
    _member_identity,
    _MultiFkMemberSpec,
    _relationship_member_spec,
    _unpack_credit_member,
)
from apps.claim_ingest.plan import RunReport
from apps.provenance.claims import (
    build_relationship_claim,
    normalize_abbreviation_value,
    normalize_alias_identity,
)
from apps.provenance.models import ChangeSet, CitationInstance, Claim, IngestRun, Source
from apps.provenance.validation import (
    FkTarget,
    RelationshipSchema,
    ValueKeySpec,
    get_relationship_schema,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _seed_flipcommons_catalog(flipcommons_catalog):
    """Patches here attribute to ``flipcommons-catalog`` by default, so seed it for
    every test. Unlike ``flip-museum`` (migration-seeded), the catalog source is
    created by the pindata ingest in prod, not a migration."""


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
attribution: flipcommons-catalog
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
    assert tag_claim.source.slug == "flipcommons-catalog"


def test_unknown_field_rejected(machine_model):
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      not_a_field: 5
"""
    with pytest.raises(PatchError, match="unknown field"):
        _apply(text)


def test_unknown_entity_type_rejected():
    text = """
attribution: flipcommons-catalog
claims:
  - frobnicator.foo:
      year: 1
"""
    with pytest.raises(PatchError):
        _apply(text)


# ── Create ─────────────────────────────────────────────────────────


def test_create_manufacturer():
    text = """
attribution: flipcommons-catalog
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
        Claim.objects.filter(
            source__slug="flipcommons-catalog", is_active=True
        ).values_list("field_name", flat=True)
    )
    assert {"slug", "name", "status"} <= keys


def test_create_resolves_padded_fk_value():
    # _lookup_pk canonicalizes FK values with the same str-cast + trim the
    # apply-time resolver uses, so a padded create FK resolves to its target
    # instead of erroring as not-found — no build-vs-apply FK drift.
    Manufacturer.objects.create(name="Acme", slug="acme-mfr")
    text = """
attribution: flipcommons-catalog
claims:
  - corporate-entity.acme-incarnation:
      create: true
      name: Acme Incarnation
      manufacturer: ' acme-mfr '
"""
    report = _apply(text, patch_id="0001-padded-fk")
    assert report.records_created == 1
    ce = CorporateEntity.objects.get(slug="acme-incarnation")
    assert ce.manufacturer.slug == "acme-mfr"


def test_create_resolves_padded_fk_to_same_patch_create():
    # The same-patch-create analogue: an FK value is canonicalized identically
    # whether the target is committed or created earlier in this patch, so a
    # padded reference reaches the earlier create via the registry
    # (created_handle) just as it reaches a committed row — no committed-vs-create
    # split.
    text = """
attribution: flipcommons-catalog
claims:
  - manufacturer.acme-mfr:
      create: true
      name: Acme
  - corporate-entity.acme-incarnation:
      create: true
      name: Acme Incarnation
      manufacturer: ' acme-mfr '
"""
    report = _apply(text, patch_id="0001-padded-fk-create")
    assert report.records_created == 2
    ce = CorporateEntity.objects.get(slug="acme-incarnation")
    assert ce.manufacturer.slug == "acme-mfr"


def test_create_when_already_exists_errors(manufacturer):
    text = f"""
attribution: flipcommons-catalog
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
attribution: flipcommons-catalog
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
attribution: flipcommons-catalog
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
attribution: flipcommons-catalog
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
attribution: flipcommons-catalog
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
attribution: flipcommons-catalog
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
attribution: flipcommons-catalog
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
attribution: flipcommons-catalog
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
attribution: flipcommons-catalog
claims:
  - manufacturer.does-not-exist:
      name: Nope
"""
    with pytest.raises(PatchError, match="no such"):
        _apply(text)


# ── Create + FK reassignment (the stern shape) ─────────────────────


def test_create_and_fk_reassignment(stern_entity, stern):
    text = """
attribution: flipcommons-catalog
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
attribution: flipcommons-catalog
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


def test_relationship_member_created_earlier_same_patch(machine_model):
    # A relationship member created by an *earlier* entry in the same patch
    # resolves via the deferred (identity_refs) path — no longer rejected.
    text = f"""
attribution: flipcommons-catalog
claims:
  - tag.brand-new-tag:
      name: Brand New Tag
      create: true
  - model.{machine_model.slug}:
      tag: [brand-new-tag]
"""
    report = _apply(text)
    assert report.rejected == 0

    tag = Tag.objects.get(slug="brand-new-tag")
    machine_model.refresh_from_db()
    assert list(machine_model.tags.values_list("slug", flat=True)) == [tag.slug]


# ── Same-patch backward references (create-first) ──────────────────


def test_backward_fk_on_create(_bootstrap_source):
    # Create a manufacturer, then create a corporate-entity whose `manufacturer`
    # FK points at it — both in one patch, the dependency declared first.
    text = """
attribution: flipcommons-catalog
claims:
  - manufacturer.western:
      create: true
      name: Western
  - corporate-entity.western-inc:
      create: true
      name: Western Inc
      manufacturer: western
"""
    report = _apply(text, patch_id="0001-western")
    assert report.rejected == 0

    mfr = Manufacturer.objects.get(slug="western")
    ce = CorporateEntity.objects.get(slug="western-inc")
    assert ce.manufacturer_id == mfr.pk
    # The FK provenance claim landed on the create.
    assert ce.claims.filter(field_name="manufacturer", is_active=True).exists()


def test_backward_fk_on_create_dry_run(_bootstrap_source):
    # Dry-run must not reject the FK-to-planned-target just because the target
    # doesn't exist yet, and must write nothing (guards the apply.py P1 carve-out).
    text = """
attribution: flipcommons-catalog
claims:
  - manufacturer.western:
      create: true
      name: Western
  - corporate-entity.western-inc:
      create: true
      name: Western Inc
      manufacturer: western
"""
    report = _apply(text, patch_id="0001-western", dry_run=True)
    assert report.rejected == 0
    assert not Manufacturer.objects.filter(slug="western").exists()
    assert not CorporateEntity.objects.filter(slug="western-inc").exists()
    assert not IngestRun.objects.filter(patch_id="0001-western").exists()


def test_backward_parent_location():
    # Create a parent location, then a child whose `parent` FK names it.
    _country("usa", "USA")
    text = """
attribution: flipcommons-catalog
claims:
  - location.usa/tx:
      create: true
      name: Texas
      slug: tx
      parent: usa
      location_type: state
  - location.usa/tx/paris:
      create: true
      name: Paris
      slug: paris
      parent: usa/tx
      location_type: city
"""
    report = _apply(text, patch_id="0001-paris")
    assert report.rejected == 0

    tx = Location.objects.get(location_path="usa/tx")
    paris = Location.objects.get(location_path="usa/tx/paris")
    assert paris.parent_id == tx.pk


def test_backward_parent_location_dry_run():
    _country("usa", "USA")
    text = """
attribution: flipcommons-catalog
claims:
  - location.usa/tx:
      create: true
      name: Texas
      slug: tx
      parent: usa
      location_type: state
  - location.usa/tx/paris:
      create: true
      name: Paris
      slug: paris
      parent: usa/tx
      location_type: city
"""
    report = _apply(text, patch_id="0001-paris", dry_run=True)
    assert report.rejected == 0
    assert not Location.objects.filter(location_path="usa/tx").exists()


def test_backward_title_then_model(williams_entity):
    # Create a Title, then a MachineModel whose `title` FK names it.
    text = """
attribution: flipcommons-catalog
claims:
  - title.foo:
      create: true
      name: Foo
  - model.foo:
      create: true
      name: Foo
      title: foo
"""
    report = _apply(text, patch_id="0001-foo")
    assert report.rejected == 0

    title = Title.objects.get(slug="foo")
    model = MachineModel.objects.get(slug="foo")
    assert model.title_id == title.pk


def test_backward_member_on_existing_entity(bally_wulff):
    # Create a Location, then assert it as a `location` relationship member on an
    # existing corporate-entity — the deferred (identity_refs) path.
    text = """
attribution: flipcommons-catalog
claims:
  - location.germany/munich:
      create: true
      name: Munich
      slug: munich
      parent: germany
      location_type: city
  - corporate-entity.bally-wulff:
      location: [germany/munich]
"""
    report = _apply(text, patch_id="0001-munich")
    assert report.rejected == 0

    munich = Location.objects.get(location_path="germany/munich")
    assert "germany/munich" in _ce_location_paths(bally_wulff)
    assert _location_claim("munich").value["location"] == munich.pk


def test_backward_member_on_created_subject(_bootstrap_source):
    # Both the relationship subject (a CE) and its member (a Location) are
    # created in this same patch — the deferred member targets the subject's
    # *handle*, not an existing row, plus a backward FK to a created manufacturer.
    _country("germany", "Germany")
    text = """
attribution: flipcommons-catalog
claims:
  - manufacturer.acme-co:
      create: true
      name: Acme Co
  - location.germany/cologne:
      create: true
      name: Cologne
      slug: cologne
      parent: germany
      location_type: city
  - corporate-entity.acme-inc:
      create: true
      name: Acme Inc
      manufacturer: acme-co
      location: [germany/cologne]
"""
    report = _apply(text, patch_id="0001-acme")
    assert report.rejected == 0

    ce = CorporateEntity.objects.get(slug="acme-inc")
    assert ce.manufacturer.slug == "acme-co"
    assert "germany/cologne" in _ce_location_paths(ce)


def test_backward_member_carries_note_and_cite(bally_wulff):
    # An entry whose relationship members are *all* same-patch creates, carrying
    # note: and cite:. The carrier must register (no spurious rejection) and the
    # note/citation must land on the resolved member claim.
    text = """
attribution: flipcommons-catalog
claims:
  - location.germany/munich:
      create: true
      name: Munich
      slug: munich
      parent: germany
      location_type: city
  - corporate-entity.bally-wulff:
      location: [germany/munich]
      note: 'flipcommons-catalog places it in Munich.'
      cite: https://example.org/bally-wulff
sources:
  - name: Example
    source_type: web
    links:
      - { url: "https://example.org/", label: Example, link_type: homepage }
"""
    report = _apply(text, patch_id="0001-munich-cite")
    assert report.rejected == 0

    claim = _location_claim("munich")
    assert claim.changeset is not None
    assert claim.changeset.note == "flipcommons-catalog places it in Munich."
    assert CitationInstance.objects.filter(claim=claim).exists()


def test_backward_duplicate_deferred_member_rejected(bally_wulff):
    # [munich, munich] with a same-patch-created munich → the same "duplicate
    # member" rejection the concrete path raises (parity for deferred members).
    text = """
attribution: flipcommons-catalog
claims:
  - location.germany/munich:
      create: true
      name: Munich
      slug: munich
      parent: germany
      location_type: city
  - corporate-entity.bally-wulff:
      location: [germany/munich, germany/munich]
"""
    with pytest.raises(PatchError, match="duplicate member"):
        _apply(text)


def test_self_parent_on_create_rejected():
    # A create that names itself as its own parent must be rejected — the patch
    # path enforces the same self-link guard as the API's plan_parent_claims.
    text = """
attribution: flipcommons-catalog
claims:
  - gameplay-feature.multiball:
      create: true
      name: Multiball
      gameplay_feature_parent: [multiball]
"""
    with pytest.raises(PatchError, match="cannot be its own"):
        _apply(text)


def test_cycle_via_edit_referencing_same_patch_create_rejected():
    # The vector same-patch refs newly enables: create a child under an existing
    # root, then point the root at the child — a 2-cycle through a created node.
    GameplayFeature.objects.create(name="Root", slug="root")
    text = """
attribution: flipcommons-catalog
claims:
  - gameplay-feature.child:
      create: true
      name: Child
      gameplay_feature_parent: [root]
  - gameplay-feature.root:
      gameplay_feature_parent: [child]
"""
    with pytest.raises(PatchError, match="cycle"):
        _apply(text)


def test_cycle_between_existing_nodes_rejected():
    # The pre-existing hole the guard also closes: two existing features pointed
    # at each other in one patch.
    GameplayFeature.objects.create(name="A", slug="a")
    GameplayFeature.objects.create(name="B", slug="b")
    text = """
attribution: flipcommons-catalog
claims:
  - gameplay-feature.a:
      gameplay_feature_parent: [b]
  - gameplay-feature.b:
      gameplay_feature_parent: [a]
"""
    with pytest.raises(PatchError, match="cycle"):
        _apply(text)


def test_valid_hierarchy_in_one_patch():
    # A genuine parent→child DAG built in one patch must NOT trip the guard.
    text = """
attribution: flipcommons-catalog
claims:
  - gameplay-feature.ramps:
      create: true
      name: Ramps
  - gameplay-feature.center-ramp:
      create: true
      name: Center Ramp
      gameplay_feature_parent: [ramps]
"""
    report = _apply(text, patch_id="0001-ramps")
    assert report.rejected == 0
    child = GameplayFeature.objects.get(slug="center-ramp")
    assert list(child.parents.values_list("slug", flat=True)) == ["ramps"]


def _feature_counts(machine_model: MachineModel) -> dict[str, int | None]:
    """slug → count for a model's materialized gameplay-feature through rows."""
    return {
        row.gameplayfeature.slug: row.count
        for row in MachineModelGameplayFeature.objects.filter(
            machinemodel=machine_model
        ).select_related("gameplayfeature")
    }


def test_gameplay_feature_count_via_mapping(machine_model):
    # Format A: a bare slug ⇒ count NULL, a one-key ``{slug: count}`` map ⇒ count.
    GameplayFeature.objects.create(name="Multiball", slug="multiball")
    GameplayFeature.objects.create(name="Flippers", slug="flippers")
    text = f"""
attribution: flipcommons-catalog
description: gameplay features with a count
claims:
  - model.{machine_model.slug}:
      gameplay_feature:
        - multiball
        - flippers: 2
"""
    report = _apply(text)
    assert report.rejected == 0
    assert _feature_counts(machine_model) == {"multiball": None, "flippers": 2}


def test_gameplay_feature_count_same_patch_create(machine_model):
    # A counted member whose feature is created earlier in the same patch must
    # still carry the count through the deferred (identity_refs) path.
    text = f"""
attribution: flipcommons-catalog
claims:
  - gameplay-feature.flippers:
      create: true
      name: Flippers
  - model.{machine_model.slug}:
      gameplay_feature:
        - flippers: 2
"""
    report = _apply(text, patch_id="0001-flippers")
    assert report.rejected == 0
    assert _feature_counts(machine_model) == {"flippers": 2}


def test_gameplay_feature_remove_by_bare_slug(machine_model):
    # count is not part of identity, so removal stays a bare slug.
    GameplayFeature.objects.create(name="Flippers", slug="flippers")
    _apply(
        f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      gameplay_feature:
        - flippers: 2
""",
        patch_id="0001-add",
    )
    assert _feature_counts(machine_model) == {"flippers": 2}
    _apply(
        f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      remove:
        gameplay_feature:
          - flippers
""",
        patch_id="0002-remove",
    )
    assert _feature_counts(machine_model) == {}


def test_tag_rejects_count_mapping(machine_model):
    # A relationship with no payload slot (tag) rejects the mapping form.
    Tag.objects.create(name="Prototype", slug="prototype")
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      tag:
        - prototype: 2
"""
    with pytest.raises(PatchError, match="must be a public_id string"):
        _apply(text)


def test_gameplay_feature_explicit_null_count(machine_model):
    # An explicit ``null`` on the nullable count slot ⇒ NULL, identical to the
    # bare-slug form. (A bare empty ``flippers:`` is the string '' — rejected below.)
    GameplayFeature.objects.create(name="Flippers", slug="flippers")
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      gameplay_feature:
        - flippers: null
"""
    report = _apply(text)
    assert report.rejected == 0
    assert _feature_counts(machine_model) == {"flippers": None}


def test_gameplay_feature_empty_count_rejected(machine_model):
    # ``- flippers:`` parses as the empty string, not null — rejected as non-int
    # rather than silently treated as "no count".
    GameplayFeature.objects.create(name="Flippers", slug="flippers")
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      gameplay_feature:
        - flippers:
"""
    with pytest.raises(PatchError, match="count must be int"):
        _apply(text)


@pytest.mark.parametrize("bad_count", [0, -1])
def test_gameplay_feature_count_must_be_positive(machine_model, bad_count):
    # The count's lower bound is the through-model field's MinValueValidator, so a
    # 0/negative count is a plan-time PatchError, not a deferred IntegrityError.
    GameplayFeature.objects.create(name="Flippers", slug="flippers")
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      gameplay_feature:
        - flippers: {bad_count}
"""
    with pytest.raises(PatchError, match="count must be >= 1"):
        _apply(text)


def test_gameplay_feature_count_must_be_int(machine_model):
    GameplayFeature.objects.create(name="Flippers", slug="flippers")
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      gameplay_feature:
        - flippers: lots
"""
    with pytest.raises(PatchError, match="count"):
        _apply(text)


def test_backward_unresolvable_ref_errors(_bootstrap_source):
    # A reference in neither the DB nor this patch → PatchError, updated message.
    text = """
attribution: flipcommons-catalog
claims:
  - corporate-entity.western-inc:
      create: true
      name: Western Inc
      manufacturer: does-not-exist
"""
    with pytest.raises(PatchError, match="not in the seed, an earlier patch"):
        _apply(text)


# ── expect: (legacy drift guard, now accepted-but-ignored) ─────────────
#
# `expect:` stays parseable so older patches that carry it still apply, but it
# no longer guards anything — a mismatch is silently ignored, not an error.


def test_expect_accepted_but_ignored_on_edit(machine_model):
    # A wrong expect: used to fail before any write; now it's ignored and the
    # edit applies anyway.
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      expect: {{ year: 1234 }}
      year: 1990
"""
    _apply(text)
    machine_model.refresh_from_db()
    assert machine_model.year == 1990


def test_expect_accepted_but_ignored_on_create():
    # expect: on a create is no longer rejected — it's simply ignored.
    text = """
attribution: flipcommons-catalog
claims:
  - manufacturer.acme-pinball:
      name: Acme
      create: true
      expect: { name: Whatever }
"""
    _apply(text)
    assert Manufacturer.objects.filter(slug="acme-pinball").exists()


# ── Retract ────────────────────────────────────────────────────────


def test_retract_must_be_a_list():
    with pytest.raises(PatchError, match="'retract' must be a list"):
        load_patch(
            "attribution: flipcommons-catalog\nclaims:\n  - model.a:\n      retract: name\n"
        )


def test_retract_fk_falls_through_to_remaining_source(
    stern, manufacturer, flipcommons_catalog
):
    # Two sources claim the manufacturer FK; retracting the winning source's
    # claim makes resolution fall through to the remaining source's value.
    catalog = flipcommons_catalog
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
    assert any("no-op" in w for w in report.warnings)


def test_retract_noop_with_note_rejected(stern):
    # A note on a retract that finds no active claim from THIS source has no
    # carrier: the retraction is a no-op, so _persist writes no ChangeSet and the
    # note would vanish silently on a reported success. Reject it — symmetric
    # with remove:'s no-op-with-note behavior — rather than drop provenance.
    ipdb = Source.objects.create(
        name="IPDB", slug="ipdb", source_type="database", priority=100
    )
    ce = CorporateEntity.objects.create(
        name="Western Products, Inc.",
        slug="western-products-incorporated",
        manufacturer=stern,
    )
    # ipdb claims `name` but not `manufacturer`, so retracting manufacturer is a
    # no-op for this source.
    Claim.objects.assert_claim(ce, "name", "Western Products, Inc.", source=ipdb)

    text = """
attribution: ipdb
claims:
  - corporate-entity.western-products-incorporated:
      retract: [manufacturer]
      note: 'ipdb no longer lists a manufacturer.'
"""
    with pytest.raises(PatchError, match="note has nothing to attach to"):
        _apply(text, patch_id="0001-noop-note")


def test_retract_real_with_note_records_changeset(stern):
    # The complement: a retract that DOES deactivate a claim carries its note
    # onto the resulting ChangeSet (the fix must not break the happy path).
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
      note: 'ipdb dropped the manufacturer attribution.'
"""
    report = _apply(text, patch_id="0001-retract-note")
    assert report.retracted == 1
    retraction = Claim.objects.get(
        source=ipdb, field_name="manufacturer", is_active=False
    )
    assert retraction.retracted_by_changeset is not None
    assert (
        retraction.retracted_by_changeset.note
        == "ipdb dropped the manufacturer attribution."
    )


def test_retract_plus_create_rejected():
    text = """
attribution: flipcommons-catalog
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
attribution: flipcommons-catalog
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
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      retract: [tag]
"""
    with pytest.raises(PatchError, match="relationship retract is unsupported"):
        _apply(text)


def test_retract_one_field_assert_another_in_same_entry(stern, flipcommons_catalog):
    # An entry may retract one field and assert a different one.
    catalog = flipcommons_catalog
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


# ── Grouped `changesets:` form ─────────────────────────────────────


def _grouped_notes(patch_id: str) -> list[str]:
    """ChangeSet notes for a patch, in apply (file) order."""
    return list(
        ChangeSet.objects.filter(ingest_run__patch_id=patch_id)
        .order_by("id")
        .values_list("note", flat=True)
    )


def test_grouped_pure_wrapper_expands(machine_model):
    # The dai-uchuu shape: one header (the ref) wrapping two separately cited
    # changesets. Parses to two EditEntrys sharing the ref; both land as their
    # own ChangeSet, in file order.
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      changesets:
        - note: first change
          player_count: 4
        - note: second change
          flipper_count: 2
"""
    doc = load_patch(text)
    assert [type(e) for e in doc.claims] == [EditEntry, EditEntry]
    assert {e.ref for e in doc.claims} == {f"model.{machine_model.slug}"}

    report = _apply(text, patch_id="0001-grouped")
    assert report.rejected == 0
    assert _grouped_notes("0001-grouped") == ["first change", "second change"]
    machine_model.refresh_from_db()
    assert machine_model.player_count == 4
    assert machine_model.flipper_count == 2


def test_grouped_header_expect_ignored(machine_model):
    # A header expect: is accepted-but-ignored; every changeset still applies
    # even when the expect would have mismatched.
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      expect: {{ year: 1234 }}
      changesets:
        - player_count: 4
        - flipper_count: 2
"""
    assert _apply(text).rejected == 0
    machine_model.refresh_from_db()
    assert (machine_model.player_count, machine_model.flipper_count) == (4, 2)


def test_grouped_disjoint_violation_across_items(machine_model):
    # Two changesets asserting the same field collapse to one claim_key — rejected
    # by the same plan-wide guard as the flat cross-entry case.
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      expect: {{ year: 1997 }}
      changesets:
        - player_count: 4
        - player_count: 2
"""
    with pytest.raises(PatchError, match="set by more than one entry"):
        _apply(text)


def test_grouped_create_header_plus_companions():
    # `create: true` header is the CreateEntry; each changesets item is a
    # companion edit on the record just created (replaces the positional dance).
    text = """
attribution: flipcommons-catalog
description: new brand with a companion edit
claims:
  - manufacturer.acme-pinball:
      create: true
      name: Acme Pinball
      changesets:
        - website: https://acme.example.com
          note: company site
"""
    report = _apply(text, patch_id="0001-acme")
    assert report.records_created == 1
    assert report.rejected == 0

    mfr = Manufacturer.objects.get(slug="acme-pinball")
    assert mfr.name == "Acme Pinball"
    assert mfr.website == "https://acme.example.com"
    assert "company site" in _grouped_notes("0001-acme")


def test_grouped_primary_edit_plus_companions(machine_model):
    # Header asserts a field (no create/delete) → it is the primary EditEntry;
    # the changesets items are siblings. All land, header first.
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      expect: {{ year: 1997 }}
      note: header note
      player_count: 4
      changesets:
        - note: companion note
          flipper_count: 2
"""
    doc = load_patch(text)
    assert [type(e) for e in doc.claims] == [EditEntry, EditEntry]
    assert doc.claims[0].note == "header note"

    report = _apply(text, patch_id="0001-primary")
    assert report.rejected == 0
    assert _grouped_notes("0001-primary") == ["header note", "companion note"]
    machine_model.refresh_from_db()
    assert (machine_model.player_count, machine_model.flipper_count) == (4, 2)


def test_grouped_delete_with_changesets_rejected(machine_model):
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      delete: true
      changesets:
        - note: orphan
"""
    with pytest.raises(PatchError, match="can't be combined with 'changesets'"):
        load_patch(text)


@pytest.mark.parametrize(
    "forbidden", ["create: true", "delete: true", "changesets: []"]
)
def test_grouped_item_header_only_key_rejected(forbidden):
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      changesets:
        - note: x
          {forbidden}
"""
    with pytest.raises(PatchError, match="header-only"):
        load_patch(text)


@pytest.mark.parametrize(
    "bad",
    [
        "changesets: []",
        "changesets: not-a-list",
        "changesets:\n        - just-a-string",
    ],
)
def test_grouped_empty_or_nonlist_changesets_rejected(bad):
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      expect: {{ year: 1997 }}
      {bad}
"""
    with pytest.raises(
        PatchError, match="non-empty list of mappings|item must be a mapping"
    ):
        load_patch(text)


def test_grouped_header_provenance_without_fields_rejected():
    # A header that is only expect: + changesets: but carries a note has nothing
    # to attach it to — clear message, not the opaque carrier error.
    text = """
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      expect: { year: 1997 }
      note: orphan note
      changesets:
        - player_count: 4
"""
    with pytest.raises(PatchError, match="put provenance on the individual changesets"):
        load_patch(text)


# ── Remove relationship member (exists=false supersede) ────────────


@pytest.fixture
def bally_wulff(db, flipcommons_catalog):
    """A CorporateEntity whose sole location is Germany, claimed by flipcommons-catalog.

    Mirrors the real case: a coarse pindata-derived location we refine to a more
    specific child (Berlin). The membership claim is attributed to
    flipcommons-catalog so a patch from the same source supersedes it; Berlin is
    seeded as a child of Germany, ready to assert.
    """
    catalog = flipcommons_catalog
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
    Claim.objects.assert_claim(ce, "name", "Bally Wulff", source=catalog)
    claim_key, value = build_relationship_claim("location", {"location": germany.pk})
    Claim.objects.assert_claim(
        ce, "location", value, source=catalog, claim_key=claim_key
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
attribution: flipcommons-catalog
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
attribution: flipcommons-catalog
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
attribution: flipcommons-catalog
claims:
  - corporate-entity.bally-wulff:
      remove: { location: [germany] }
      note: 'flipcommons-catalog says "headquartered in Berlin".'
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
    assert (
        tombstone.changeset.note
        == 'flipcommons-catalog says "headquartered in Berlin".'
    )
    assert CitationInstance.objects.filter(claim=tombstone).exists()


def test_remove_must_be_a_mapping():
    text = (
        "attribution: flipcommons-catalog\nclaims:\n"
        "  - corporate-entity.a:\n      remove: [location]\n"
    )
    with pytest.raises(PatchError, match="'remove' must be a mapping"):
        load_patch(text)


def test_remove_scalar_field_rejected(bally_wulff):
    # A scalar/FK field isn't a relationship namespace — point the author at
    # retract: instead.
    text = """
attribution: flipcommons-catalog
claims:
  - corporate-entity.bally-wulff:
      remove: { manufacturer: [williams] }
"""
    with pytest.raises(PatchError, match="not a relationship namespace"):
        _apply(text)


def test_remove_relationship_not_valid_on_subject(bally_wulff):
    # 'theme' is a relationship namespace, but not on CorporateEntity.
    text = """
attribution: flipcommons-catalog
claims:
  - corporate-entity.bally-wulff:
      remove: { theme: [medieval] }
"""
    with pytest.raises(PatchError, match="is not valid on"):
        _apply(text)


def test_remove_unknown_member_rejected(bally_wulff):
    text = """
attribution: flipcommons-catalog
claims:
  - corporate-entity.bally-wulff:
      remove: { location: [atlantis] }
"""
    with pytest.raises(PatchError, match="does not resolve"):
        _apply(text)


def test_remove_noop_when_source_lacks_claim(bally_wulff):
    # flipcommons-catalog never claimed Berlin membership, so removing it writes no
    # tombstone — a warning, not an error, so re-running a patch stays safe.
    text = """
attribution: flipcommons-catalog
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
attribution: flipcommons-catalog
claims:
  - corporate-entity.bally-wulff:
      remove: { location: [germany/berlin] }
      note: 'flipcommons-catalog says "not in Berlin".'
"""
    with pytest.raises(PatchError, match="note has nothing to attach to"):
        _apply(text, patch_id="0001-noop-note")


def test_remove_and_assert_same_member_rejected(bally_wulff):
    # Asserting a member present and removing it in one patch would write the
    # same claim_key twice with opposite exists — reject the contradiction.
    text = """
attribution: flipcommons-catalog
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
    # currently claim the member (so the removal is a no-op). flipcommons-catalog claims
    # germany, not germany/berlin, so the remove here is a no-op.
    text = """
attribution: flipcommons-catalog
claims:
  - corporate-entity.bally-wulff:
      location: [germany/berlin]
      remove: { location: [germany/berlin] }
"""
    with pytest.raises(PatchError, match="cannot both assert and remove"):
        _apply(text)


def test_remove_plus_create_rejected():
    text = """
attribution: flipcommons-catalog
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
attribution: flipcommons-catalog
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
attribution: flipcommons-catalog
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
attribution: flipcommons-catalog
claims:
  - corporate-entity.williams-electronics:
      delete: true
"""
    with pytest.raises(PatchError, match="cannot delete.*still referenced"):
        _apply(text, patch_id="0001-del")
    assert not Claim.objects.filter(
        source__slug="flipcommons-catalog", field_name="status"
    ).exists()


def test_delete_blocked_caught_in_dry_run(machine_model):
    # The blocker check is a build-phase DB read, so --dry-run surfaces it too.
    text = """
attribution: flipcommons-catalog
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
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      expect: {{ corporate_entity: williams-electronics }}
      corporate_entity: stern-pinball-inc
"""
    _apply(reassign, patch_id="0001-reassign")
    machine_model.refresh_from_db()
    assert machine_model.corporate_entity_id == stern_entity.pk

    delete = """
attribution: flipcommons-catalog
claims:
  - corporate-entity.williams-electronics:
      delete: true
"""
    report = _apply(delete, patch_id="0002-delete")
    assert report.rejected == 0
    williams = CorporateEntity.objects.get(slug="williams-electronics")
    assert williams.status == "deleted"


def test_reassign_fk_onto_deleted_root_rejected(machine_model, stern_entity):
    # The onto-hole: reassign the machine's corporate_entity *onto* stern, then
    # delete stern — in ONE patch. The committed delete-blocker can't see the
    # machine point at stern (it still points at williams in the DB), so the
    # delete would proceed and leave the machine dangling at a soft-deleted
    # entity. The build-time guard rejects it: an FK claim targets an entity the
    # same patch deletes.
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      corporate_entity: stern-pinball-inc
  - corporate-entity.stern-pinball-inc:
      delete: true
"""
    with pytest.raises(PatchError, match="points at"):
        _apply(text, patch_id="0001-onto-root")
    stern_entity.refresh_from_db()
    assert stern_entity.status != "deleted"


def test_reassign_fk_onto_deleted_cascade_child_rejected(machine_model, db):
    # Same hole, but the deleted entity is a *cascade child*, not the root.
    # Deleting the Title cascades to its MachineModel (medieval-madness); a second
    # machine reassigns variant_of onto medieval-madness in the same patch. The
    # guard must intersect the FK target with the whole cascade footprint, not
    # only the delete root.
    other_title = Title.objects.create(name="Other Title", slug="other-title")
    MachineModel.objects.create(name="Other Pin", slug="other-pin", title=other_title)
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.other-pin:
      variant_of: {machine_model.slug}
  - title.medieval-madness-title:
      delete: true
"""
    with pytest.raises(PatchError, match="points at"):
        _apply(text, patch_id="0001-onto-cascade")
    machine_model.refresh_from_db()
    assert machine_model.status is None  # delete did not proceed


def test_create_with_fk_onto_deleted_rejected(db, flipcommons_catalog):
    # The `_lookup_pk` mirror: a *create* whose FK targets a same-patch-deleted
    # entity produces the identical dangling row, and an edit-scoped scan would
    # miss it (creates carry no perturbed cell). The fresh manufacturer has no
    # other referrers, so only the onto-guard — not the delete-blocker — can catch
    # this.
    Manufacturer.objects.create(name="Doomed Brand", slug="doomed-brand")
    text = """
attribution: flipcommons-catalog
claims:
  - corporate-entity.new-incarnation:
      create: true
      name: New Incarnation
      manufacturer: doomed-brand
  - manufacturer.doomed-brand:
      delete: true
"""
    with pytest.raises(PatchError, match="points at"):
        _apply(text, patch_id="0001-onto-create")
    assert Manufacturer.objects.get(slug="doomed-brand").status != "deleted"
    assert not CorporateEntity.objects.filter(slug="new-incarnation").exists()


def test_reassign_onto_live_entity_not_rejected(machine_model, stern_entity):
    # Negative pin: the guard fires only when the onto-target is *deleted*.
    # Reassigning the machine onto stern (a live entity nobody deletes) is an
    # ordinary edit and must pass.
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      corporate_entity: stern-pinball-inc
"""
    report = _apply(text, patch_id="0001-onto-live")
    assert report.rejected == 0
    machine_model.refresh_from_db()
    assert machine_model.corporate_entity_id == stern_entity.pk


def test_losing_fk_reassign_onto_deleted_still_rejected(machine_model, stern_entity):
    # Documented over-coverage: the guard is *syntactic* (on the FK claim target),
    # not on the resolved post-patch FK. A higher-priority source pins the
    # machine's corporate_entity to williams, so the patch's stern claim *loses*
    # resolution — yet because the patch still asserts corporate_entity=stern and
    # deletes stern, the guard rejects it. Rejecting a pointless point-at-X-and-
    # delete-X claim is the strict, defensible choice.
    authority = Source.objects.create(
        name="Authority", slug="authority", source_type="editorial", priority=900
    )
    Claim.objects.assert_claim(
        machine_model, "corporate_entity", "williams-electronics", source=authority
    )
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      corporate_entity: stern-pinball-inc
  - corporate-entity.stern-pinball-inc:
      delete: true
"""
    with pytest.raises(PatchError, match="points at"):
        _apply(text, patch_id="0001-onto-losing")
    stern_entity.refresh_from_db()
    assert stern_entity.status != "deleted"


def test_reassign_fk_onto_deleted_normalizes_whitespace(machine_model, stern_entity):
    # The guard must canonicalize FK values exactly as apply-time resolution does
    # (_resolve_fk_generic str-casts and trims). A whitespace-padded value would
    # otherwise slip the raw-string guard yet still resolve the live machine onto
    # stern after the same patch deletes it — a dangling reference.
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      corporate_entity: ' stern-pinball-inc '
  - corporate-entity.stern-pinball-inc:
      delete: true
"""
    with pytest.raises(PatchError, match="points at"):
        _apply(text, patch_id="0001-onto-ws")
    stern_entity.refresh_from_db()
    assert stern_entity.status != "deleted"


def test_reassign_fk_onto_deleted_normalizes_numeric(machine_model, manufacturer):
    # A non-str FK value (YAML int) must not skip the guard: apply resolves it via
    # str(value).strip(), so a numeric slug-like value dangles just the same.
    doomed = CorporateEntity.objects.create(
        name="Numbered", slug="1234", manufacturer=manufacturer
    )
    Claim.objects.assert_claim(
        doomed,
        "name",
        "Numbered",
        source=Source.objects.get(slug="flipcommons-catalog"),
    )
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      corporate_entity: 1234
  - corporate-entity.1234:
      delete: true
"""
    with pytest.raises(PatchError, match="points at"):
        _apply(text, patch_id="0001-onto-num")
    doomed.refresh_from_db()
    assert doomed.status != "deleted"


def test_referrer_itself_deleted_onto_target_rejected(machine_model, stern_entity):
    # The second documented over-coverage shape: the row reassigned *onto* stern is
    # itself deleted in the same patch (so post-apply it wouldn't actually dangle).
    # The syntactic guard rejects it anyway — point-at-X and delete-X in one file —
    # exactly as it rejects a losing claim. Here the machine's own Title is deleted,
    # cascading the machine to status=deleted.
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      corporate_entity: stern-pinball-inc
  - title.medieval-madness-title:
      delete: true
  - corporate-entity.stern-pinball-inc:
      delete: true
"""
    with pytest.raises(PatchError, match="points at"):
        _apply(text, patch_id="0001-onto-self-del")
    stern_entity.refresh_from_db()
    assert stern_entity.status != "deleted"


def test_delete_is_idempotent(stern_entity):
    text = """
attribution: flipcommons-catalog
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


def test_delete_with_expect_ignored(stern_entity):
    # expect: on a delete is accepted-but-ignored; the delete applies even when
    # the expect would have mismatched.
    text = """
attribution: flipcommons-catalog
claims:
  - corporate-entity.stern-pinball-inc:
      expect: { manufacturer: williams }
      delete: true
"""
    _apply(text)
    stern_entity.refresh_from_db()
    assert stern_entity.status == "deleted"


def test_delete_nonexistent_rejected():
    text = """
attribution: flipcommons-catalog
claims:
  - corporate-entity.no-such-entity:
      delete: true
"""
    with pytest.raises(PatchError, match="no such corporate-entity to delete"):
        _apply(text)


def test_delete_with_create_rejected():
    text = """
attribution: flipcommons-catalog
claims:
  - corporate-entity.acme:
      create: true
      delete: true
"""
    with pytest.raises(PatchError, match="mutually exclusive"):
        _apply(text)


def test_delete_with_retract_rejected(stern_entity):
    text = """
attribution: flipcommons-catalog
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
attribution: flipcommons-catalog
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
attribution: flipcommons-catalog
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
attribution: flipcommons-catalog
claims:
  - corporate-entity.williams-electronics:
      status: deleted
"""
    with pytest.raises(PatchError, match="'status' is lifecycle"):
        _apply(text)
    assert not Claim.objects.filter(
        source__slug="flipcommons-catalog", field_name="status"
    ).exists()


def test_delete_cascade_child_other_entry_rejected(machine_model):
    # Decision 5: deleting a Title cascades status=deleted onto its MachineModels;
    # the delete footprint is exclusive, so a separate entry touching a cascaded
    # child (reached only via the cascade) is rejected.
    text = """
attribution: flipcommons-catalog
claims:
  - title.medieval-madness-title:
      delete: true
  - model.medieval-madness:
      note: 'edit on a machine that the cascade is deleting'
      year: 1998
"""
    with pytest.raises(PatchError, match="another entry targets an entity this patch"):
        _apply(text)


def test_cascade_delete_is_one_changeset(machine_model):
    # Decision 5: a standalone cascading delete (Title → MachineModel) yields ONE
    # multi-entity ChangeSet spanning root + cascade, matching the in-app delete.
    text = """
attribution: flipcommons-catalog
claims:
  - title.medieval-madness-title:
      delete: true
"""
    _apply(text, patch_id="0009-del")
    changesets = ChangeSet.objects.filter(ingest_run__patch_id="0009-del")
    assert changesets.count() == 1
    cs = changesets.get()
    deleted = cs.claims.filter(field_name="status", value="deleted")
    # status=deleted on both the Title (root) and its cascaded MachineModel.
    assert deleted.count() == 2


def test_delete_must_be_boolean():
    with pytest.raises(PatchError, match="'delete' must be a boolean"):
        load_patch(
            "attribution: flipcommons-catalog\nclaims:\n"
            "  - corporate-entity.x:\n      delete: yes\n"
        )


def test_delete_note_and_cite_attach_to_status_claim(stern_entity):
    text = """
attribution: flipcommons-catalog
claims:
  - corporate-entity.stern-pinball-inc:
      delete: true
      note: 'flipcommons-catalog says "this firm never existed".'
      cite: https://example.org/proof
sources:
  - name: Example
    source_type: web
    links:
      - { url: "https://example.org/", label: Example, link_type: homepage }
"""
    _apply(text, patch_id="0001-del")
    status_claim = Claim.objects.get(
        source__slug="flipcommons-catalog", field_name="status", is_active=True
    )
    assert status_claim.value == "deleted"
    changeset = status_claim.changeset
    assert changeset is not None
    assert changeset.note == 'flipcommons-catalog says "this firm never existed".'
    assert CitationInstance.objects.filter(claim=status_claim).exists()


# ── Empty directives on an incompatible kind (strict parse) ────────
# An empty no-op directive (expect: {}, retract: [], remove: {}) on a kind that
# structurally can't carry it is rejected at *parse* time, not silently ignored.
# This is a deliberate tightening over the old truthiness check (`if pc.expect:`
# was falsy on an empty value, so empties slipped through). It's pinned as a
# contract because load_patch runs on every file on every ingest — a parse rule
# is part of the format, and a future relaxation would be a real semantic change.


@pytest.mark.parametrize(
    ("directive", "match"),
    [
        ("retract: []", "meaningless on a create"),
        ("remove: {}", "meaningless on a create"),
    ],
)
def test_empty_directive_on_create_rejected(directive, match):
    text = f"""
attribution: flipcommons-catalog
claims:
  - manufacturer.acme:
      create: true
      name: Acme
      {directive}
"""
    with pytest.raises(PatchError, match=match):
        load_patch(text)


@pytest.mark.parametrize("directive", ["retract: []", "remove: {}"])
def test_empty_directive_on_delete_rejected(directive):
    text = f"""
attribution: flipcommons-catalog
claims:
  - corporate-entity.acme:
      delete: true
      {directive}
"""
    with pytest.raises(PatchError, match="mutually exclusive"):
        load_patch(text)


def test_empty_directives_on_edit_are_accepted(machine_model):
    # The strict rejection is scoped to create/delete. An edit may still carry
    # empty no-op directives (they resolve to no-ops), so the tightening didn't
    # over-reach — guard against a future over-correction.
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      year: 1990
      expect: {{}}
      retract: []
      remove: {{}}
"""
    report = _apply(text)
    assert report.rejected == 0
    machine_model.refresh_from_db()
    assert machine_model.year == 1990


# ── Idempotency (engine-level no-op) ───────────────────────────────


def test_reassert_same_claim_is_noop(machine_model):
    text = f"""
attribution: flipcommons-catalog
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
attribution: flipcommons-catalog
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
    return Source.objects.get(slug="flipcommons-catalog")


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
attribution: flipcommons-catalog
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
        f"attribution: flipcommons-catalog\nclaims:\n  - model.{machine_model.slug}:\n      year: 1990\n",
        encoding="utf-8",
    )
    call_command("ingest_patches", "--patches-dir", str(tmp_path))

    # Semantic change to an applied patch → hard error.
    p.write_text(
        f"attribution: flipcommons-catalog\nclaims:\n  - model.{machine_model.slug}:\n      year: 1991\n",
        encoding="utf-8",
    )
    with pytest.raises(CommandError, match="immutable"):
        call_command("ingest_patches", "--patches-dir", str(tmp_path))


def test_command_immutability_cosmetic_reformat_skips(tmp_path, machine_model):
    p = tmp_path / "0001-year.yaml"
    p.write_text(
        f"attribution: flipcommons-catalog\nclaims:\n  - model.{machine_model.slug}:\n      year: 1990\n",
        encoding="utf-8",
    )
    call_command("ingest_patches", "--patches-dir", str(tmp_path))

    # Cosmetic reformat (added comment + blank lines + spacing) → still skips.
    p.write_text(
        f"# a comment\nattribution:   flipcommons-catalog\n\nclaims:\n\n  - model.{machine_model.slug}:\n      year: 1990\n",
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
    _write(
        tmp_path, "not-numbered.yaml", "attribution: flipcommons-catalog\nclaims: []\n"
    )
    with pytest.raises(CommandError, match="NNNN-slug"):
        call_command("ingest_patches", "--patches-dir", str(tmp_path))


def test_command_preflight_duplicate_prefix(tmp_path):
    _write(tmp_path, "0001-a.yaml", "attribution: flipcommons-catalog\nclaims: []\n")
    _write(tmp_path, "0001-b.yaml", "attribution: flipcommons-catalog\nclaims: []\n")
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
        f"attribution: flipcommons-catalog\nclaims:\n  - model.{machine_model.slug}:\n      year: 1990\n",
    )
    _write(
        tmp_path,
        "0002-bad.yaml",
        "attribution: flipcommons-catalog\nclaims:\n  - manufacturer.nope:\n      name: Nope\n",
    )
    _write(
        tmp_path,
        "0003-later.yaml",
        f"attribution: flipcommons-catalog\nclaims:\n  - model.{machine_model.slug}:\n      year: 1992\n",
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
        "attribution: flipcommons-catalog\n"
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
attribution: flipcommons-catalog
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
        load_patch("attribution: flipcommons-catalog\nclaims: []\n")


def test_sources_missing_name_rejected():
    with pytest.raises(PatchError, match="'name' is required"):
        load_patch("attribution: flipcommons-catalog\nsources:\n  - source_type: web\n")


def test_sources_unknown_key_rejected():
    text = (
        "attribution: flipcommons-catalog\n"
        "sources:\n"
        "  - name: X\n"
        "    source_type: web\n"
        "    descriptoin: typo\n"
    )
    with pytest.raises(PatchError, match="unknown key"):
        load_patch(text)


def test_sources_children_rejected():
    text = (
        "attribution: flipcommons-catalog\n"
        "sources:\n"
        "  - name: X\n"
        "    source_type: web\n"
        "    children: []\n"
    )
    with pytest.raises(PatchError, match="children"):
        load_patch(text)


def test_sources_link_missing_url_rejected():
    text = (
        "attribution: flipcommons-catalog\n"
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
    return f"attribution: flipcommons-catalog\nsources:\n  - {node_body}\n"


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
        "attribution: flipcommons-catalog\n"
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
attribution: flipcommons-catalog
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
attribution: flipcommons-catalog
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


# ── Alias & abbreviation relationship members (string identity) ────


def _alias_values(mfr: Manufacturer) -> set[str]:
    return set(mfr.aliases.values_list("value", flat=True))


def _alias_claim(value_lower: str) -> Claim:
    """The active 'manufacturer_alias' claim for the lowercased identity."""
    claim_key, _ = build_relationship_claim(
        "manufacturer_alias", {"alias_value": value_lower}
    )
    return Claim.objects.get(
        claim_key=claim_key, field_name="manufacturer_alias", is_active=True
    )


def test_assert_manufacturer_alias(stern):
    text = """
attribution: flipcommons-catalog
claims:
  - manufacturer.stern:
      manufacturer_alias: [Stern Pinball]
"""
    report = _apply(text)
    assert report.rejected == 0

    stern.refresh_from_db()
    assert _alias_values(stern) == {"Stern Pinball"}

    claim = _alias_claim("stern pinball")
    assert claim.value == {
        "alias_value": "stern pinball",
        "alias_display": "Stern Pinball",
        "exists": True,
    }
    # Parity: the emitted claim_key is byte-identical to what the editor's
    # build_relationship_claim produces from the same identity — the heart of
    # the feature.
    expected_key, _ = build_relationship_claim(
        "manufacturer_alias",
        {"alias_value": "stern pinball", "alias_display": "Stern Pinball"},
    )
    assert claim.claim_key == expected_key


def test_assert_abbreviation(machine_model):
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      abbreviation: [MM]
"""
    report = _apply(text)
    assert report.rejected == 0

    assert set(machine_model.abbreviations.values_list("value", flat=True)) == {"MM"}
    claim_key, _ = build_relationship_claim("abbreviation", {"value": "MM"})
    claim = Claim.objects.get(
        claim_key=claim_key, field_name="abbreviation", is_active=True
    )
    # No case-folding: abbreviations are stored verbatim.
    assert claim.value == {"value": "MM", "exists": True}


def test_remove_alias_tombstone_parity(stern):
    # An earlier patch asserts two aliases; a later one removes one. The dropped
    # member's tombstone must be lowercased and carry NO alias_display.
    assert_text = """
attribution: flipcommons-catalog
claims:
  - manufacturer.stern:
      manufacturer_alias: [Stern Pinball, Stern Inc]
"""
    _apply(assert_text, patch_id="0001-aliases")
    stern.refresh_from_db()
    assert _alias_values(stern) == {"Stern Pinball", "Stern Inc"}

    remove_text = """
attribution: flipcommons-catalog
claims:
  - manufacturer.stern:
      remove: { manufacturer_alias: [Stern Inc] }
"""
    report = _apply(remove_text, patch_id="0002-drop-alias")
    assert report.rejected == 0

    stern.refresh_from_db()
    assert _alias_values(stern) == {"Stern Pinball"}

    tombstone = _alias_claim("stern inc")
    # Exact tombstone shape: lowercased, with display-only fields omitted.
    assert tombstone.value == {"alias_value": "stern inc", "exists": False}
    expected_key, _ = build_relationship_claim(
        "manufacturer_alias", {"alias_value": "stern inc"}, exists=False
    )
    assert tombstone.claim_key == expected_key


def test_remove_alias_noop_when_source_lacks_claim(stern):
    # flipcommons-catalog never claimed this alias, so removing it warns (no-op) and
    # writes no tombstone — re-running a patch stays safe.
    text = """
attribution: flipcommons-catalog
claims:
  - manufacturer.stern:
      remove: { manufacturer_alias: [Never Claimed] }
"""
    report = _apply(text, patch_id="0001-noop-alias")
    assert report.rejected == 0
    assert any("no-op" in w for w in report.warnings)
    claim_key, _ = build_relationship_claim(
        "manufacturer_alias", {"alias_value": "never claimed"}
    )
    assert not Claim.objects.filter(claim_key=claim_key).exists()


def test_reassert_alias_is_unchanged(stern):
    # Re-asserting the same alias from the same source diffs as unchanged.
    text = """
attribution: flipcommons-catalog
claims:
  - manufacturer.stern:
      manufacturer_alias: [Stern Pinball]
"""
    _apply(text, patch_id="0001-first")
    first = _alias_claim("stern pinball")
    report = _apply(text, patch_id="0002-again")
    assert report.rejected == 0
    second = _alias_claim("stern pinball")
    # Same active claim row — no new claim written for an unchanged re-assert.
    assert second.pk == first.pk


def test_credit_bare_string_member_rejected(machine_model):
    # 'credit' is a multi-key (person + role) relationship: a member must be a
    # one-key '{person: role}' mapping, not the bare public_id a single-key
    # relationship takes. Confirms the multi-FK arm validates shape (no fixtures
    # needed — it rejects before resolving).
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      credit: [pat-lawlor]
"""
    with pytest.raises(PatchError, match="single 'person: role' mapping"):
        _apply(text)


def test_non_string_identity_rejected(monkeypatch):
    # The gate keys on scalar_type, not just fk_target. No prod schema has a
    # single non-FK, non-str identity, so craft one and monkeypatch the lookup —
    # no global registry mutation (a successful register would persist).
    crafted = RelationshipSchema(
        namespace="fake_int_identity",
        value_keys=(
            ValueKeySpec(
                name="amount",
                scalar_type=int,
                required=True,
                identity="amount",
            ),
        ),
        valid_subjects=frozenset({Manufacturer}),
    )
    monkeypatch.setattr(
        "apps.claim_ingest.patches.emit.get_relationship_schema",
        lambda namespace: crafted if namespace == "fake_int_identity" else None,
    )
    entry = EditEntry(
        entity_type="manufacturer",
        public_id="stern",
        retract=[],
        remove={},
        fields={},
    )
    with pytest.raises(PatchError, match="non-FK, non-string identity"):
        _relationship_member_spec(Manufacturer, "fake_int_identity", entry)


def test_mixed_multi_key_identity_rejected(monkeypatch):
    # A multi-key identity is authorable only when every slot is an FK. No prod
    # schema mixes an FK and a non-FK identity slot, so craft one — the gate must
    # reject it rather than classify it as a multi-FK member.
    crafted = RelationshipSchema(
        namespace="fake_mixed_multikey",
        value_keys=(
            ValueKeySpec(
                name="person",
                scalar_type=int,
                required=True,
                identity="person",
                fk_target=FkTarget(Person, "pk"),
            ),
            ValueKeySpec(
                name="amount",
                scalar_type=int,
                required=True,
                identity="amount",
            ),
        ),
        valid_subjects=frozenset({Manufacturer}),
    )
    monkeypatch.setattr(
        "apps.claim_ingest.patches.emit.get_relationship_schema",
        lambda namespace: crafted if namespace == "fake_mixed_multikey" else None,
    )
    entry = EditEntry(
        entity_type="manufacturer",
        public_id="stern",
        retract=[],
        remove={},
        fields={},
    )
    with pytest.raises(PatchError, match="not all-FK"):
        _relationship_member_spec(Manufacturer, "fake_mixed_multikey", entry)


def test_more_than_two_fk_slots_not_authorable():
    # The one-key '{a: b}' mapping encodes exactly two values, so a hypothetical
    # >2-slot multi-FK relationship has no authoring syntax. No prod schema has
    # one, so build the spec directly and confirm the unpack guard rejects it.
    spec = _MultiFkMemberSpec(
        slots=(
            _FkMemberSpec(value_key="person", target_model=Person),
            _FkMemberSpec(value_key="role", target_model=CreditRole),
            _FkMemberSpec(value_key="extra", target_model=Manufacturer),
        )
    )
    entry = EditEntry(
        entity_type="manufacturer",
        public_id="stern",
        retract=[],
        remove={},
        fields={},
    )
    with pytest.raises(PatchError, match="only 2-slot members are authorable"):
        _unpack_credit_member({"a": "b"}, spec, "fake_three_fk", entry)


def test_payload_on_non_single_fk_rejected(monkeypatch):
    # A non-identity payload slot is authorable only via the one-key
    # '{public_id: value}' form, which only a single-FK shape uses. A multi-FK
    # (or any non-single-FK) shape carrying one has no syntax for it. No prod
    # schema does this, so craft one and confirm registration-time rejection.
    crafted = RelationshipSchema(
        namespace="fake_multikey_payload",
        value_keys=(
            ValueKeySpec(
                name="person",
                scalar_type=int,
                required=True,
                identity="person",
                fk_target=FkTarget(Person, "pk"),
            ),
            ValueKeySpec(
                name="role",
                scalar_type=int,
                required=True,
                identity="role",
                fk_target=FkTarget(CreditRole, "pk"),
            ),
            ValueKeySpec(name="weight", scalar_type=int, required=False, nullable=True),
        ),
        valid_subjects=frozenset({Manufacturer}),
    )
    monkeypatch.setattr(
        "apps.claim_ingest.patches.emit.get_relationship_schema",
        lambda namespace: crafted if namespace == "fake_multikey_payload" else None,
    )
    entry = EditEntry(
        entity_type="manufacturer",
        public_id="stern",
        retract=[],
        remove={},
        fields={},
    )
    with pytest.raises(PatchError, match="no authoring syntax"):
        _relationship_member_spec(Manufacturer, "fake_multikey_payload", entry)


def test_multiple_payload_slots_rejected(monkeypatch):
    # The one-key '{public_id: value}' form encodes exactly one extra value, so a
    # single-FK shape can carry at most one payload slot. Craft a two-payload one.
    crafted = RelationshipSchema(
        namespace="fake_two_payload",
        value_keys=(
            ValueKeySpec(
                name="feature",
                scalar_type=int,
                required=True,
                identity="feature",
                fk_target=FkTarget(GameplayFeature, "pk"),
            ),
            ValueKeySpec(name="count", scalar_type=int, required=False, nullable=True),
            ValueKeySpec(name="note", scalar_type=str, required=False, nullable=True),
        ),
        valid_subjects=frozenset({Manufacturer}),
    )
    monkeypatch.setattr(
        "apps.claim_ingest.patches.emit.get_relationship_schema",
        lambda namespace: crafted if namespace == "fake_two_payload" else None,
    )
    entry = EditEntry(
        entity_type="manufacturer",
        public_id="stern",
        retract=[],
        remove={},
        fields={},
    )
    with pytest.raises(PatchError, match="not patch-authorable"):
        _relationship_member_spec(Manufacturer, "fake_two_payload", entry)


def test_media_attachment_not_patch_authorable():
    # media_attachment is a *real* registered single-FK schema (media_asset)
    # carrying two non-identity slots — category and is_primary. It is authored
    # through the media API, never via data patches, so the multi-payload guard
    # must reject it. Pinned on the real schema, not a synthetic stand-in, so a
    # future media-schema change that made it look patch-authorable is caught here.
    entry = EditEntry(
        entity_type="model",
        public_id="x",
        retract=[],
        remove={},
        fields={},
    )
    with pytest.raises(PatchError, match="not patch-authorable"):
        _relationship_member_spec(MachineModel, "media_attachment", entry)


# ── Credits (multi-key: person + role) ─────────────────────────────


def _credit_claim(person_pk: int, role_slug: str) -> Claim:
    """The active 'credit' claim for ``(person_pk, role)``."""
    role = CreditRole.objects.get(slug=role_slug)
    claim_key, _ = build_relationship_claim(
        "credit", {"person": person_pk, "role": role.pk}
    )
    return Claim.objects.get(claim_key=claim_key, field_name="credit", is_active=True)


def test_credit_on_model_with_citation(machine_model, person, credit_roles):
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      cite: https://example.org/mm-credits
      credit:
        - pat-lawlor: design
sources:
  - name: Example
    source_type: web
    links:
      - {{ url: "https://example.org/", label: Example, link_type: homepage }}
"""
    report = _apply(text)
    assert report.rejected == 0

    assert Credit.objects.filter(
        model=machine_model, person=person, role__slug="design"
    ).exists()
    # The entry-level cite: rides the credit claim like any scalar/FK claim.
    assert CitationInstance.objects.filter(
        claim=_credit_claim(person.pk, "design")
    ).exists()


def test_credit_on_series(person, credit_roles):
    series = Series.objects.create(name="World Cup Soccer", slug="world-cup-soccer")
    text = f"""
attribution: flipcommons-catalog
claims:
  - series.{series.slug}:
      credit:
        - pat-lawlor: design
"""
    report = _apply(text)
    assert report.rejected == 0
    # Exercises the Phase 1 series resolver through the patch path.
    assert Credit.objects.filter(
        series=series, person=person, role__slug="design"
    ).exists()


def test_credit_same_person_two_roles(machine_model, person, credit_roles):
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      credit:
        - pat-lawlor: design
        - pat-lawlor: software
"""
    report = _apply(text)
    assert report.rejected == 0
    assert Credit.objects.filter(model=machine_model, person=person).count() == 2


def test_credit_same_patch_create_person(another_model, credit_roles):
    # Person slot defers to a same-patch create; role slot is committed.
    text = f"""
attribution: flipcommons-catalog
claims:
  - person.jane-newcomer:
      create: true
      name: Jane Newcomer
  - model.{another_model.slug}:
      credit:
        - jane-newcomer: art
"""
    report = _apply(text)
    assert report.rejected == 0
    jane = Person.objects.get(slug="jane-newcomer")
    assert Credit.objects.filter(
        model=another_model, person=jane, role__slug="art"
    ).exists()


def test_credit_same_patch_create_person_and_role(another_model):
    # BOTH slots defer to same-patch creates — no credit_roles fixture, the role
    # is created in the patch. Exercises the second identity slot's deferral and
    # the composite deferred-key path that the person-only case leaves unhit.
    text = f"""
attribution: flipcommons-catalog
claims:
  - person.dana-newcomer:
      create: true
      name: Dana Newcomer
  - credit-role.lead-designer:
      create: true
      name: Lead Designer
  - model.{another_model.slug}:
      credit:
        - dana-newcomer: lead-designer
"""
    report = _apply(text)
    assert report.rejected == 0
    dana = Person.objects.get(slug="dana-newcomer")
    assert Credit.objects.filter(
        model=another_model, person=dana, role__slug="lead-designer"
    ).exists()


def test_credit_two_persons_share_created_role(another_model):
    # Two persons crediting the *same* same-patch-created role both defer on the
    # one role handle. Keyed by the bare handle they would collide as a false
    # "duplicate member"; the composite (person, role) deferred key keeps them
    # distinct. Regression guard for the disjoint-key construction.
    text = f"""
attribution: flipcommons-catalog
claims:
  - credit-role.co-designer:
      create: true
      name: Co-Designer
  - person.amy-one:
      create: true
      name: Amy One
  - person.ben-two:
      create: true
      name: Ben Two
  - model.{another_model.slug}:
      credit:
        - amy-one: co-designer
        - ben-two: co-designer
"""
    report = _apply(text)
    assert report.rejected == 0
    assert (
        Credit.objects.filter(model=another_model, role__slug="co-designer").count()
        == 2
    )


def test_credit_remove(machine_model, person, credit_roles):
    add = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      credit:
        - pat-lawlor: design
"""
    _apply(add, patch_id="0001-add")
    assert Credit.objects.filter(model=machine_model, person=person).exists()

    remove = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      remove:
        credit:
          - pat-lawlor: design
"""
    report = _apply(remove, patch_id="0002-remove")
    assert report.rejected == 0
    assert not Credit.objects.filter(model=machine_model, person=person).exists()


def test_credit_remove_absent_is_noop(machine_model, person, credit_roles):
    # Removing a credit this source never claimed is a logged no-op, not an error.
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      remove:
        credit:
          - pat-lawlor: design
"""
    report = _apply(text)
    assert report.rejected == 0
    assert not Credit.objects.filter(model=machine_model).exists()


def test_credit_idempotent(machine_model, person, credit_roles):
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      credit:
        - pat-lawlor: design
"""
    _apply(text, patch_id="0001-x")
    first = _credit_claim(person.pk, "design")
    _apply(text, patch_id="0002-x")
    second = _credit_claim(person.pk, "design")
    # Unchanged re-assert: same active claim row, single Credit.
    assert second.pk == first.pk
    assert Credit.objects.filter(model=machine_model).count() == 1


def test_credit_unknown_person_rejected(machine_model, credit_roles):
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      credit:
        - nobody-here: design
"""
    with pytest.raises(PatchError, match="does not resolve to a Person"):
        _apply(text)


def test_credit_unknown_role_rejected(machine_model, person, credit_roles):
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      credit:
        - pat-lawlor: no-such-role
"""
    with pytest.raises(PatchError, match="does not resolve to a CreditRole"):
        _apply(text)


def test_credit_non_string_value_rejected(machine_model, person, credit_roles):
    # A role slug YAML reads as a number (unquoted) is a non-string value → the
    # shape guard rejects it (the quoting gotcha the docs warn about).
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      credit:
        - pat-lawlor: 1979
"""
    with pytest.raises(PatchError, match="single 'person: role' mapping"):
        _apply(text)


def test_credit_multi_key_member_rejected(machine_model, person, credit_roles):
    # A two-key mapping is not a single 'person: role' member.
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      credit:
        - pat-lawlor: design
          john-youssi: art
"""
    with pytest.raises(PatchError, match="single 'person: role' mapping"):
        _apply(text)


def test_credit_duplicate_member_in_entry_rejected(machine_model, person, credit_roles):
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      credit:
        - pat-lawlor: design
        - pat-lawlor: design
"""
    with pytest.raises(PatchError, match="duplicate member"):
        _apply(text)


def test_credit_assert_and_remove_same_member_rejected(
    machine_model, person, credit_roles
):
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      credit:
        - pat-lawlor: design
      remove:
        credit:
          - pat-lawlor: design
"""
    with pytest.raises(PatchError, match="cannot both assert and remove"):
        _apply(text)


def test_alias_over_length_rejected(stern):
    long_alias = "x" * 201  # alias_value bound is 200
    text = f"""
attribution: flipcommons-catalog
claims:
  - manufacturer.stern:
      manufacturer_alias: ["{long_alias}"]
"""
    with pytest.raises(PatchError, match="exceeds the 200-character limit"):
        _apply(text, dry_run=True)


def test_abbreviation_over_length_rejected(machine_model):
    long_abbr = "y" * 51  # abbreviation value bound is 50
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      abbreviation: ["{long_abbr}"]
"""
    with pytest.raises(PatchError, match="exceeds the 50-character limit"):
        _apply(text, dry_run=True)


def test_schema_carries_max_length():
    # A future refactor that drops the registration-time population must fail
    # loudly here, not silently re-open the over-length trap.
    abbr = get_relationship_schema("abbreviation")
    assert abbr is not None
    (abbr_id,) = [s for s in abbr.value_keys if s.identity is not None]
    assert abbr_id.max_length == 50

    alias = get_relationship_schema("manufacturer_alias")
    assert alias is not None
    (alias_id,) = [s for s in alias.value_keys if s.identity is not None]
    assert alias_id.max_length == 200


def test_intra_list_duplicate_alias_rejected(stern):
    # Stern and stern fold to the same identity → same claim_key twice.
    text = """
attribution: flipcommons-catalog
claims:
  - manufacturer.stern:
      manufacturer_alias: [Stern, stern]
"""
    with pytest.raises(PatchError, match="duplicate member"):
        _apply(text)


def test_intra_list_duplicate_abbreviation_rejected(machine_model):
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      abbreviation: [MM, MM]
"""
    with pytest.raises(PatchError, match="duplicate member"):
        _apply(text)


def test_intra_list_duplicate_in_remove_rejected(stern):
    # The remove path dedups by the same fold → claim_key as the assert path.
    text = """
attribution: flipcommons-catalog
claims:
  - manufacturer.stern:
      remove: { manufacturer_alias: [Stern Inc, stern inc] }
"""
    with pytest.raises(PatchError, match="duplicate member"):
        _apply(text)


def test_blank_alias_member_rejected(stern):
    text = """
attribution: flipcommons-catalog
claims:
  - manufacturer.stern:
      manufacturer_alias: ["   "]
"""
    with pytest.raises(PatchError, match="blank member"):
        _apply(text)


def test_blank_abbreviation_member_rejected(machine_model):
    text = f"""
attribution: flipcommons-catalog
claims:
  - model.{machine_model.slug}:
      abbreviation: ["   "]
"""
    with pytest.raises(PatchError, match="blank member"):
        _apply(text)


def test_member_identity_shares_canonical_fold():
    # The patch path and the shared fold helpers produce identical bytes — the
    # structural guard that editor and patch consume one fold. Pure registry +
    # fold; no DB rows needed.
    entry = EditEntry(
        entity_type="manufacturer",
        public_id="stern",
        retract=[],
        remove={},
        fields={},
    )
    alias_spec = _relationship_member_spec(Manufacturer, "manufacturer_alias", entry)
    ident = _member_identity("Stern Pinball", "manufacturer_alias", alias_spec, entry)
    folded = normalize_alias_identity("Stern Pinball")
    assert ident == {
        "alias_value": folded.value,
        "alias_display": folded.display,
    }

    abbr_entry = EditEntry(
        entity_type="model",
        public_id="medieval-madness",
        retract=[],
        remove={},
        fields={},
    )
    abbr_spec = _relationship_member_spec(MachineModel, "abbreviation", abbr_entry)
    abbr_ident = _member_identity("MedMad", "abbreviation", abbr_spec, abbr_entry)
    assert abbr_ident == {"value": normalize_abbreviation_value("MedMad")}
