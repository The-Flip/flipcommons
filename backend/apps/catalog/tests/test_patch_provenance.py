"""Tests for per-entry patch ``note:`` and ``cite:`` provenance.

Covers parsing + build_plan validation, the apply-time effects (ChangeSet
note, citation source get-or-create, per-claim CitationInstance attachment),
and the documented v1 limitations (create scaffolding uncited, citation on an
unchanged claim no-ops).
"""

from __future__ import annotations

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from apps.catalog.ingestion.apply import (
    CitationRef,
    IngestPlan,
    PlannedClaimAssert,
    apply_plan,
)
from apps.catalog.ingestion.patches import (
    EditEntry,
    PatchError,
    build_plan,
    load_patch,
)
from apps.catalog.models import MachineModel, Manufacturer, Tag
from apps.catalog.tests.conftest import make_machine_model
from apps.citation.models import CitationSource
from apps.provenance.models import (
    ChangeSet,
    CitationInstance,
    Claim,
    IngestRun,
    Source,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def ipdb_root(db):
    """The root CitationSource for the ipdb scheme (children hang under it)."""
    return CitationSource.objects.create(
        name="Internet Pinball Database",
        source_type="web",
        identifier_key="ipdb",
    )


@pytest.fixture
def kineticist_root(db):
    """A non-scheme root web source with a homepage link, for domain matching."""
    root = CitationSource.objects.create(name="Kineticist", source_type="web")
    root.links.create(link_type="homepage", url="https://kineticist.com/")
    return root


@pytest.fixture
def pm(db, flipcommons_catalog):
    return make_machine_model(
        name="Medieval Madness", slug="medieval-madness", year=1997
    )


@pytest.fixture
def prototype_tag(db):
    return Tag.objects.create(name="Prototype", slug="prototype")


def _apply(text: str, *, patch_id: str = "0001-test", dry_run: bool = False):
    doc = load_patch(text)
    source = Source.objects.get(slug=doc.attribution)
    plan = build_plan(doc, source=source, patch_id=patch_id)
    return apply_plan(plan, dry_run=dry_run)


# ── Parsing ────────────────────────────────────────────────────────


def test_note_and_cite_parsed_and_excluded_from_fields():
    doc = load_patch(
        "attribution: flipcommons-catalog\n"
        "claims:\n"
        "  - model.x:\n"
        "      note: tagged because the name says so\n"
        "      cite: ipdb:4443\n"
        "      year: 1990\n"
    )
    (entry,) = doc.claims
    assert isinstance(entry, EditEntry)  # no create/delete → an edit
    assert entry.note == "tagged because the name says so"
    assert entry.cite == "ipdb:4443"
    assert entry.fields == {"year": 1990}  # note/cite are not field assertions


def test_note_must_be_string():
    with pytest.raises(PatchError, match="note"):
        load_patch("attribution: a\nclaims:\n  - model.x:\n      note: [1, 2]\n")


# ── build_plan validation ──────────────────────────────────────────


def test_bad_cite_format_rejected(flipcommons_catalog, pm):
    text = "attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n      cite: ipdb\n      year: 1998\n"
    with pytest.raises(PatchError, match="scheme:identifier"):
        _apply(text)


def test_unknown_cite_scheme_rejected(flipcommons_catalog, pm):
    text = "attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n      cite: bogus:4443\n      year: 1998\n"
    with pytest.raises(PatchError, match="unknown cite scheme"):
        _apply(text)


def test_invalid_cite_identifier_rejected(flipcommons_catalog, pm):
    # ipdb ids are digits; a non-numeric id fails normalization.
    text = "attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n      cite: ipdb:not-a-number\n      year: 1998\n"
    with pytest.raises(PatchError, match="invalid ipdb identifier"):
        _apply(text)


def test_overlong_note_rejected(flipcommons_catalog, pm):
    long_note = "x" * 1001
    text = (
        "attribution: flipcommons-catalog\n"
        "claims:\n"
        "  - model.medieval-madness:\n"
        f"      note: {long_note}\n"
        "      year: 1998\n"
    )
    with pytest.raises(PatchError, match="note exceeds"):
        _apply(text)


def test_multiple_disjoint_edits_one_entity(flipcommons_catalog, ipdb_root, pm):
    # Per-entry ChangeSets: two entries may edit one entity when their fields are
    # disjoint. Each entry is its own ChangeSet with its own note + citation; pk
    # order follows file order.
    text = """
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      note: corrected year per the flyer
      cite: ipdb:4443
      year: 1998
  - model.medieval-madness:
      note: production figure from the archive
      production_quantity: 4000
"""
    report = _apply(text)
    assert report.asserted == 2

    assert IngestRun.objects.filter(patch_id="0001-test").count() == 1
    changesets = list(
        ChangeSet.objects.filter(ingest_run__patch_id="0001-test").order_by("pk")
    )
    assert len(changesets) == 2
    assert changesets[0].note == "corrected year per the flyer"
    assert changesets[1].note == "production figure from the archive"

    year_claim = pm.claims.get(field_name="year", is_active=True)
    qty_claim = pm.claims.get(field_name="production_quantity", is_active=True)
    # pk/file order: first entry → first changeset, second entry → second.
    assert year_claim.changeset_id == changesets[0].pk
    assert qty_claim.changeset_id == changesets[1].pk
    # Citation rode only the first entry's claim.
    assert year_claim.citation_instances.exists()
    assert not qty_claim.citation_instances.exists()


def test_no_note_multi_entry_still_groups_per_entry(flipcommons_catalog, pm):
    # Two disjoint-field edits, neither carrying a note → still two ChangeSets,
    # each owning its claim (grouping rides entry_index, not the note).
    text = """
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      year: 1998
  - model.medieval-madness:
      production_quantity: 4000
"""
    _apply(text)
    assert ChangeSet.objects.filter(ingest_run__patch_id="0001-test").count() == 2


def test_same_field_two_entries_rejected(flipcommons_catalog, pm):
    # Decision 2: two entries asserting the SAME field on one entity would
    # collapse to a single claim in _build_claims — rejected as non-disjoint.
    text = """
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      note: first
      year: 1998
  - model.medieval-madness:
      year: 1999
"""
    with pytest.raises(PatchError, match="more than one entry"):
        _apply(text)


def test_same_field_retracted_twice_rejected(flipcommons_catalog, pm):
    # Decision 2 (retractions): two entries retracting the same field collapse to
    # one deactivation, dropping one entry's note — rejected.
    Claim.objects.assert_claim(pm, "year", 1998, source=flipcommons_catalog)
    text = """
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      note: drop it
      retract: [year]
  - model.medieval-madness:
      note: drop it again
      retract: [year]
"""
    with pytest.raises(PatchError, match="more than one entry"):
        _apply(text)


def test_same_deferred_member_two_entries_rejected(flipcommons_catalog, pm):
    # Decision 2 (deferred member): two entries adding the SAME same-patch-created
    # tag to one model collapse to one membership claim — rejected.
    text = """
attribution: flipcommons-catalog
claims:
  - tag.newtag:
      create: true
      name: New Tag
  - model.medieval-madness:
      note: first
      tag: [newtag]
  - model.medieval-madness:
      tag: [newtag]
"""
    with pytest.raises(PatchError, match="more than one entry"):
        _apply(text)


def test_cite_on_retraction_only_entry_rejected(flipcommons_catalog, pm):
    # A cite has nothing to attach to when the entry only retracts.
    Claim.objects.assert_claim(pm, "year", 1998, source=flipcommons_catalog)
    text = "attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n      cite: ipdb:4443\n      retract: [year]\n"
    with pytest.raises(PatchError, match="cite has no field to attach to"):
        _apply(text)


def test_cite_on_fieldless_create_rejected(flipcommons_catalog):
    text = "attribution: flipcommons-catalog\nclaims:\n  - manufacturer.acme:\n      create: true\n      cite: ipdb:4443\n"
    with pytest.raises(PatchError, match="cite has no field to attach to"):
        _apply(text)


def test_cite_on_empty_relationship_rejected(flipcommons_catalog, pm):
    # `tag: []` has a field key but emits zero claims, so the cite would attach
    # to nothing — a field *key* isn't a carrier.
    text = "attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n      cite: ipdb:4443\n      tag: []\n"
    with pytest.raises(PatchError, match="cite has no field to attach to"):
        _apply(text)


def test_note_with_no_carrier_rejected(flipcommons_catalog, pm):
    # note: alongside only an empty relationship emits no claim/changeset, so
    # the note would silently vanish.
    text = "attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n      note: this goes nowhere\n      tag: []\n"
    with pytest.raises(PatchError, match="note has nothing to attach to"):
        _apply(text)


def test_duplicate_create_rejected(flipcommons_catalog):
    # Two creates for the same ref would mint a duplicate handle; build_plan
    # rejects it as a PatchError rather than letting it surface as a ValueError
    # deep in the apply layer (which ingest_patches doesn't catch).
    text = """
attribution: flipcommons-catalog
claims:
  - manufacturer.acme:
      create: true
      name: Acme One
  - manufacturer.acme:
      create: true
      name: Acme Two
"""
    with pytest.raises(PatchError, match="duplicate create entry"):
        _apply(text)


# ── apply: note → ChangeSet.note ───────────────────────────────────


def test_note_sets_changeset_note(flipcommons_catalog, pm):
    text = "attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n      note: corrected per the flyer\n      year: 1998\n"
    _apply(text)
    cs = ChangeSet.objects.get(ingest_run__isnull=False)
    assert cs.note == "corrected per the flyer"


def test_retract_only_entry_lands_note(flipcommons_catalog, pm):
    # Seed a flipcommons-catalog year claim, then retract it with a note. A retraction
    # emits no assertion, so its note must still reach the changeset.
    Claim.objects.assert_claim(pm, "year", 1998, source=flipcommons_catalog)
    text = "attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n      note: removing our bad year\n      retract: [year]\n"
    report = _apply(text, patch_id="0002-retract")
    assert report.retracted == 1
    cs = ChangeSet.objects.get(ingest_run__patch_id="0002-retract")
    assert cs.note == "removing our bad year"


# ── apply: cite → CitationSource + CitationInstance ────────────────


def test_cite_creates_source_and_attaches_to_claims(
    flipcommons_catalog, ipdb_root, pm, prototype_tag
):
    text = """
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      note: only one prototype made
      cite: ipdb:4443
      year: 1998
      tag: [prototype]
"""
    _apply(text)

    child = CitationSource.objects.get(parent=ipdb_root, identifier="4443")
    assert child.name == "Internet Pinball Database #4443"
    link = child.links.get()
    assert link.url == "https://www.ipdb.org/machine.cgi?id=4443"
    # A record page is a child, so 'reference' — homepage is for roots only.
    assert link.link_type == "reference"

    # Citation attached to BOTH the scalar (year) and relationship (tag) claims.
    year_claim = pm.claims.get(field_name="year", is_active=True)
    tag_claim = pm.claims.get(field_name="tag", is_active=True)
    assert year_claim.citation_instances.get().citation_source_id == child.pk
    assert tag_claim.citation_instances.get().citation_source_id == child.pk


def test_cite_is_idempotent_across_applications(flipcommons_catalog, ipdb_root, pm):
    base = "attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n      cite: ipdb:4443\n      year: {year}\n"
    _apply(base.format(year=1998), patch_id="0001-a")
    _apply(base.format(year=1999), patch_id="0002-b")
    # Re-citing the same id reuses the one child source.
    assert (
        CitationSource.objects.filter(parent=ipdb_root, identifier="4443").count() == 1
    )


def test_create_scaffolding_not_cited(flipcommons_catalog, ipdb_root):
    # A create entry's authored field (name) is cited; the adapter-owned slug
    # and status claims are not.
    text = """
attribution: flipcommons-catalog
claims:
  - manufacturer.acme:
      create: true
      cite: ipdb:4443
      name: Acme Pinball
"""
    _apply(text)
    acme = Manufacturer.objects.get(slug="acme")
    name_claim = acme.claims.get(field_name="name", is_active=True)
    slug_claim = acme.claims.get(field_name="slug", is_active=True)
    status_claim = acme.claims.get(field_name="status", is_active=True)
    assert name_claim.citation_instances.exists()
    assert not slug_claim.citation_instances.exists()
    assert not status_claim.citation_instances.exists()


# ── Phase 2: create + companion edits on a same-patch-created record ───


def test_create_then_companion_edit_two_changesets(flipcommons_catalog, ipdb_root):
    # A create may be followed by an edit on the same new record (resolved via the
    # same-patch create registry). Each entry mints its own ChangeSet with its own
    # note + citation; both claims land on the one created record, pk = file order.
    text = """
attribution: flipcommons-catalog
claims:
  - manufacturer.acme:
      create: true
      note: founding record
      cite: ipdb:4443
      name: Acme Pinball
  - manufacturer.acme:
      note: added the website
      cite: ipdb:5556
      website: https://acme.example
"""
    report = _apply(text)
    assert report.records_created == 1

    run = IngestRun.objects.get(patch_id="0001-test")
    # A companion edit on a same-patch create does not count as a matched record.
    assert run.records_matched == 0
    changesets = list(
        ChangeSet.objects.filter(ingest_run__patch_id="0001-test").order_by("pk")
    )
    assert len(changesets) == 2
    assert changesets[0].note == "founding record"
    assert changesets[1].note == "added the website"

    acme = Manufacturer.objects.get(slug="acme")
    name_claim = acme.claims.get(field_name="name", is_active=True)
    website_claim = acme.claims.get(field_name="website", is_active=True)
    # Both claims target the one created record, in distinct file-order ChangeSets.
    assert name_claim.changeset_id == changesets[0].pk
    assert website_claim.changeset_id == changesets[1].pk
    assert name_claim.citation_instances.exists()
    assert website_claim.citation_instances.exists()


def test_create_then_companion_edit_dry_run(flipcommons_catalog, ipdb_root):
    # The create+companion case validates clean at --dry-run: the companion's
    # handle-targeted assertions route through the planned/sentinel path, and the
    # empty-diff guard exempts handle assertions (a new record always changes).
    text = """
attribution: flipcommons-catalog
claims:
  - manufacturer.acme:
      create: true
      name: Acme Pinball
  - manufacturer.acme:
      note: added the website
      website: https://acme.example
"""
    report = _apply(text, dry_run=True)
    assert report.asserted  # validated, nothing raised
    assert not Manufacturer.objects.filter(slug="acme").exists()


def test_create_companion_same_field_rejected(flipcommons_catalog):
    # Decision 2 spans the create + its companions: the same field asserted by the
    # create and a companion edit would collapse to one claim — rejected.
    text = """
attribution: flipcommons-catalog
claims:
  - manufacturer.acme:
      create: true
      name: Acme Pinball
  - manufacturer.acme:
      name: Acme Pinball Co
"""
    with pytest.raises(PatchError, match="more than one entry"):
        _apply(text)


def test_create_companion_same_slug_rejected(flipcommons_catalog):
    # The create's adapter-owned slug claim is contributed to the disjoint guard,
    # so a companion re-asserting slug is caught even though _add_create emits it
    # outside the field loop.
    text = """
attribution: flipcommons-catalog
claims:
  - manufacturer.acme:
      create: true
      name: Acme Pinball
  - manufacturer.acme:
      slug: acme
"""
    with pytest.raises(PatchError, match="more than one entry"):
        _apply(text)


def test_create_companion_same_deferred_member_rejected(flipcommons_catalog):
    # Decision 2 (deferred member) across a create + companion: both assert the
    # same same-patch parent on the created record → one membership claim → rejected.
    text = """
attribution: flipcommons-catalog
claims:
  - theme.sports:
      create: true
      name: Sports
  - theme.baseball:
      create: true
      name: Baseball
      theme_parent: [sports]
  - theme.baseball:
      note: reassert the parent
      theme_parent: [sports]
"""
    with pytest.raises(PatchError, match="more than one entry"):
        _apply(text)


def test_edit_above_create_rejected(flipcommons_catalog):
    # Decision 6: a create must precede the edits that refine it. An edit above its
    # create resolves nowhere (the registry is single-pass) and the pre-scan names
    # the below-file create in the diagnostic.
    text = """
attribution: flipcommons-catalog
claims:
  - manufacturer.acme:
      website: https://acme.example
  - manufacturer.acme:
      create: true
      name: Acme Pinball
"""
    with pytest.raises(PatchError, match="created later in this patch"):
        _apply(text)


def test_expect_on_same_patch_create_rejected(flipcommons_catalog):
    # A same-patch create has no prior DB state to drift-guard against.
    text = """
attribution: flipcommons-catalog
claims:
  - manufacturer.acme:
      create: true
      name: Acme Pinball
  - manufacturer.acme:
      expect: { name: Acme Pinball }
      website: https://acme.example
"""
    with pytest.raises(PatchError, match="'expect:' can't guard a record created"):
        _apply(text)


def test_retract_on_same_patch_create_rejected(flipcommons_catalog):
    # No prior claims exist on a same-patch create, so retract: is meaningless.
    text = """
attribution: flipcommons-catalog
claims:
  - manufacturer.acme:
      create: true
      name: Acme Pinball
  - manufacturer.acme:
      retract: [name]
"""
    with pytest.raises(PatchError, match="'retract:' can't apply to a record created"):
        _apply(text)


def test_remove_on_same_patch_create_rejected(flipcommons_catalog):
    # No prior members exist on a same-patch create, so remove: is meaningless.
    text = """
attribution: flipcommons-catalog
claims:
  - theme.sports:
      create: true
      name: Sports
  - theme.baseball:
      create: true
      name: Baseball
  - theme.baseball:
      remove: { theme_parent: [sports] }
"""
    with pytest.raises(PatchError, match="'remove:' can't apply to a record created"):
        _apply(text)


def test_delete_on_same_patch_create_generic_message(flipcommons_catalog):
    # A delete of a same-patch create falls through to the generic "no such X to
    # delete" — deleting a record you just created in the same patch is nonsense,
    # and the create registry isn't consulted for deletes.
    text = """
attribution: flipcommons-catalog
claims:
  - manufacturer.acme:
      create: true
      name: Acme Pinball
  - manufacturer.acme:
      delete: true
"""
    with pytest.raises(PatchError, match="no such manufacturer to delete"):
        _apply(text)


def test_cite_on_unchanged_value_rejected(flipcommons_catalog, ipdb_root, pm):
    # Decision 3: an already-correct, same-source value diffs as unchanged, so a
    # cite: would attach to nothing and silently vanish — now a hard error. The
    # empty-diff guard runs in the apply layer (ValidationError; the command
    # converts it to a PatchError for the author).
    Claim.objects.assert_claim(pm, "year", 2000, source=flipcommons_catalog)
    text = "attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n      cite: ipdb:4443\n      year: 2000\n"
    with pytest.raises(ValidationError, match="changes nothing"):
        _apply(text)
    assert not CitationInstance.objects.exists()


def test_note_on_unchanged_value_rejected(flipcommons_catalog, pm):
    # Decision 3: re-asserting an already-active same-source value with a note
    # diffs as unchanged, which would drop the note — now a hard error. Build time
    # can't catch this (it depends on the post-diff result), so the apply-layer
    # empty-diff guard does.
    Claim.objects.assert_claim(pm, "year", 2000, source=flipcommons_catalog)
    text = "attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n      note: confirmed correct\n      year: 2000\n"
    with pytest.raises(ValidationError, match="changes nothing"):
        _apply(text)
    assert not ChangeSet.objects.filter(ingest_run__isnull=False).exists()


def test_empty_diff_rejected_at_dry_run(flipcommons_catalog, pm):
    # The empty-diff guard must fire at --dry-run too, so an author's pre-flight
    # check catches the no-op note before apply — not only at apply time.
    Claim.objects.assert_claim(pm, "year", 2000, source=flipcommons_catalog)
    text = "attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n      note: confirmed correct\n      year: 2000\n"
    with pytest.raises(ValidationError, match="changes nothing"):
        _apply(text, dry_run=True)


def test_changing_note_entry_passes_dry_run(flipcommons_catalog, pm):
    # A real change carrying a note validates clean at --dry-run (no false reject).
    Claim.objects.assert_claim(pm, "year", 2000, source=flipcommons_catalog)
    text = "attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n      note: corrected per the flyer\n      year: 1999\n"
    report = _apply(text, dry_run=True)
    assert report.asserted == 1


def test_dry_run_invalid_value_reports_validation_not_empty_diff(
    flipcommons_catalog, pm
):
    # An invalid value carrying a note must surface as a validation error at
    # --dry-run, not be masked by the empty-diff guard as "changes nothing": a
    # rejected claim never reaches the diff, so the guard would otherwise blame the
    # entry for a no-op instead of the real problem (year is a positive int).
    text = "attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n      note: bumping the year\n      year: -5\n"
    report = _apply(text, dry_run=True)  # must not raise "changes nothing"
    assert report.rejected == 1
    assert report.errors


def test_attach_citations_is_per_claim(flipcommons_catalog, ipdb_root, pm):
    # Direct IngestPlan: two assertions on one entity, only one carries a
    # citation_ref. The citation must ride only that claim — never bleed onto
    # the other claim that merely shares the entity.
    ct = ContentType.objects.get_for_model(MachineModel)
    plan = IngestPlan(
        source=flipcommons_catalog, input_fingerprint="fp", patch_id="0001-direct"
    )
    plan.assertions.append(
        PlannedClaimAssert(
            field_name="year",
            value=1998,
            content_type_id=ct.pk,
            object_id=pm.pk,
            citation_ref=CitationRef("ipdb", "4443"),
            entry_index=0,
        )
    )
    plan.assertions.append(
        PlannedClaimAssert(
            field_name="production_quantity",
            value=4000,
            content_type_id=ct.pk,
            object_id=pm.pk,
            entry_index=1,
        )
    )
    apply_plan(plan)

    year_claim = pm.claims.get(field_name="year", is_active=True)
    qty_claim = pm.claims.get(field_name="production_quantity", is_active=True)
    assert year_claim.citation_instances.exists()
    assert not qty_claim.citation_instances.exists()


def test_patch_plan_missing_entry_index_raises(flipcommons_catalog, pm):
    # Structural guard: a patch_id plan whose assertion lacks an entry_index would
    # silently collapse all ChangeSet grouping. The coupling check rejects it
    # before the live/dry-run split, so --dry-run catches it too. Internal
    # invariant (the adapter always stamps) → ValueError, not PatchError.
    ct = ContentType.objects.get_for_model(MachineModel)
    plan = IngestPlan(
        source=flipcommons_catalog, input_fingerprint="fp", patch_id="0001-bad"
    )
    plan.assertions.append(
        PlannedClaimAssert(
            field_name="year",
            value=1998,
            content_type_id=ct.pk,
            object_id=pm.pk,
        )  # entry_index left unset
    )
    with pytest.raises(ValueError, match="without an entry_index"):
        apply_plan(plan, dry_run=True)


def test_retract_note_on_already_inactive_field_rejected(flipcommons_catalog, pm):
    # Decision 3 (retraction note): a retract: + note: on a field this source does
    # not actively claim emits no RetractEntry, so the note would vanish. Caught at
    # build time — a no-op retraction carries nothing.
    text = "attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n      note: removing a year we never claimed\n      retract: [year]\n"
    with pytest.raises(PatchError, match="note has nothing to attach to"):
        _apply(text)


def test_missing_citation_root_errors(flipcommons_catalog, pm):
    # No ipdb root seeded → a clear error, not a silent miss.
    text = "attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n      cite: ipdb:4443\n      year: 1998\n"
    with pytest.raises(CitationSource.DoesNotExist, match="No root CitationSource"):
        _apply(text)


# ── cite: URL form → web CitationSource nested under a root ────────


def test_url_cite_without_matching_root_errors(flipcommons_catalog, pm):
    # A URL whose domain matches no seeded website root is rejected — a patch
    # must nest evidence under a curated root, not mint a parentless (abstract)
    # web source. The author seeds the root in an earlier patch first.
    url = "https://pinside.com/pinball/forum/topic/mm-prototype"
    text = (
        "attribution: flipcommons-catalog\n"
        "claims:\n"
        "  - model.medieval-madness:\n"
        f"      cite: {url}\n"
        "      year: 1998\n"
    )
    with pytest.raises(CitationSource.DoesNotExist, match="No website .*root"):
        _apply(text)


def test_url_cite_reuses_preexisting_source(flipcommons_catalog, pm):
    # A source a curator already linked to this exact URL is reused, not
    # duplicated.
    url = "https://example.com/evidence"
    existing = CitationSource.objects.create(name="Curated", source_type="web")
    existing.links.create(link_type="reference", url=url)
    text = (
        "attribution: flipcommons-catalog\n"
        "claims:\n"
        "  - model.medieval-madness:\n"
        f"      cite: {url}\n"
        "      year: 1998\n"
    )
    _apply(text)
    year_claim = pm.claims.get(field_name="year", is_active=True)
    assert year_claim.citation_instances.get().citation_source_id == existing.pk
    assert CitationSource.objects.filter(links__url=url).distinct().count() == 1


def test_url_cite_nests_under_domain_matched_root(
    flipcommons_catalog, kineticist_root, pm
):
    # A URL whose domain matches a seeded root becomes a child under that root,
    # not a flat parentless orphan.
    url = "https://kineticist.com/reviews/medieval-madness"
    text = (
        "attribution: flipcommons-catalog\n"
        "claims:\n"
        "  - model.medieval-madness:\n"
        f"      cite: {url}\n"
        "      year: 1998\n"
    )
    _apply(text)

    child = CitationSource.objects.get(parent=kineticist_root)
    link = child.links.get()
    assert link.url == url
    # The article page is evidence, not a domain homepage — typing it
    # 'reference' keeps it from ever masquerading as a root in recognition.
    assert link.link_type == "reference"
    # No orphan parentless web source was minted alongside the root.
    assert (
        not CitationSource.objects.filter(source_type="web", parent__isnull=True)
        .exclude(pk=kineticist_root.pk)
        .exists()
    )

    year_claim = pm.claims.get(field_name="year", is_active=True)
    assert year_claim.citation_instances.get().citation_source_id == child.pk


def test_url_cite_under_root_dedups_and_separates(
    flipcommons_catalog, kineticist_root, pm
):
    # Same URL twice → one child; a different path on the same domain → a second
    # child under the same root.
    base = (
        "attribution: flipcommons-catalog\n"
        "claims:\n"
        "  - model.medieval-madness:\n"
        "      cite: {url}\n"
        "      year: {year}\n"
    )
    url_a = "https://kineticist.com/a"
    url_b = "https://kineticist.com/b"
    _apply(base.format(url=url_a, year=1998), patch_id="0001-a")
    _apply(base.format(url=url_a, year=1999), patch_id="0002-a2")
    _apply(base.format(url=url_b, year=2000), patch_id="0003-b")

    assert CitationSource.objects.filter(parent=kineticist_root).count() == 2


def test_url_cite_with_archive_attaches_both_links(
    flipcommons_catalog, kineticist_root, pm
):
    # cite: {url, archive} → the child carries BOTH a 'reference' link (the live
    # page) and an 'archive' link (the Wayback snapshot): one citation, two links.
    url = "https://kineticist.com/reviews/medieval-madness"
    archive = "https://web.archive.org/web/20240101000000/" + url
    text = (
        "attribution: flipcommons-catalog\n"
        "claims:\n"
        "  - model.medieval-madness:\n"
        "      cite:\n"
        f"        url: {url}\n"
        f"        archive: {archive}\n"
        "      year: 1998\n"
    )
    _apply(text)

    child = CitationSource.objects.get(parent=kineticist_root)
    links = {link.link_type: link.url for link in child.links.all()}
    assert links == {"reference": url, "archive": archive}

    year_claim = pm.claims.get(field_name="year", is_active=True)
    assert year_claim.citation_instances.get().citation_source_id == child.pk


def test_url_cite_archive_idempotent(flipcommons_catalog, kineticist_root, pm):
    # Re-applying the same {url, archive} cite never duplicates the archive link.
    url = "https://kineticist.com/x"
    archive = "https://web.archive.org/web/20240101000000/" + url
    base = (
        "attribution: flipcommons-catalog\n"
        "claims:\n"
        "  - model.medieval-madness:\n"
        "      cite:\n"
        f"        url: {url}\n"
        f"        archive: {archive}\n"
        "      year: {year}\n"
    )
    _apply(base.format(year=1998), patch_id="0001-a")
    _apply(base.format(year=1999), patch_id="0002-b")

    child = CitationSource.objects.get(parent=kineticist_root)
    assert child.links.filter(link_type="archive").count() == 1
    assert CitationSource.objects.filter(parent=kineticist_root).count() == 1


def test_archive_added_to_preexisting_child(flipcommons_catalog, kineticist_root, pm):
    # A first patch cites the live URL (no archive); a later patch re-cites it
    # with an archive → the archive link is added to the existing child source,
    # exercising the `existing is not None` branch + the archive backfill.
    url = "https://kineticist.com/x"
    archive = "https://web.archive.org/web/20240101000000/" + url
    _apply(
        "attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n"
        f"      cite: {url}\n      year: 1998\n",
        patch_id="0001-a",
    )
    _apply(
        "attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n"
        "      cite:\n"
        f"        url: {url}\n        archive: {archive}\n"
        "      year: 1999\n",
        patch_id="0002-b",
    )

    child = CitationSource.objects.get(parent=kineticist_root)
    links = {link.link_type: link.url for link in child.links.all()}
    assert links == {"reference": url, "archive": archive}
    assert CitationSource.objects.filter(parent=kineticist_root).count() == 1


def test_cite_archive_with_scheme_cite_rejected(flipcommons_catalog, pm):
    # An archive snapshot only makes sense for a live web page, not a scheme cite.
    text = (
        "attribution: flipcommons-catalog\n"
        "claims:\n"
        "  - model.medieval-madness:\n"
        "      cite:\n"
        "        url: ipdb:4443\n"
        "        archive: https://web.archive.org/web/2024/x\n"
        "      year: 1998\n"
    )
    with pytest.raises(PatchError, match="only valid alongside"):
        _apply(text)


def test_cite_mapping_unknown_key_rejected(flipcommons_catalog, pm):
    text = (
        "attribution: flipcommons-catalog\n"
        "claims:\n"
        "  - model.medieval-madness:\n"
        "      cite:\n"
        "        url: https://kineticist.com/x\n"
        "        wayback: https://web.archive.org/x\n"
        "      year: 1998\n"
    )
    with pytest.raises(PatchError, match="unknown key"):
        _apply(text)


def test_invalid_archive_url_rejected(flipcommons_catalog, kineticist_root, pm):
    text = (
        "attribution: flipcommons-catalog\n"
        "claims:\n"
        "  - model.medieval-madness:\n"
        "      cite:\n"
        "        url: https://kineticist.com/x\n"
        "        archive: not-a-url\n"
        "      year: 1998\n"
    )
    with pytest.raises(PatchError, match="not a valid"):
        _apply(text)


def test_ipdb_url_cite_rejected(flipcommons_catalog, pm):
    # A known-scheme record URL must be cited via scheme:identifier so it dedups.
    text = (
        "attribution: flipcommons-catalog\n"
        "claims:\n"
        "  - model.medieval-madness:\n"
        "      cite: https://www.ipdb.org/machine.cgi?id=4443\n"
        "      year: 1998\n"
    )
    with pytest.raises(PatchError, match="matches the ipdb scheme.*ipdb:4443"):
        _apply(text)


def test_opdb_url_cite_rejected(flipcommons_catalog, pm):
    text = (
        "attribution: flipcommons-catalog\n"
        "claims:\n"
        "  - model.medieval-madness:\n"
        "      cite: https://opdb.org/machines/GRhX5\n"
        "      year: 1998\n"
    )
    with pytest.raises(PatchError, match="matches the opdb scheme"):
        _apply(text)


def test_malformed_url_cite_rejected(flipcommons_catalog, pm):
    text = (
        "attribution: flipcommons-catalog\n"
        "claims:\n"
        "  - model.medieval-madness:\n"
        "      cite: https://\n"
        "      year: 1998\n"
    )
    with pytest.raises(PatchError, match="is not a valid URL"):
        _apply(text)


def test_overlong_url_cite_rejected(flipcommons_catalog, pm):
    long_url = "https://example.com/" + "x" * 2000
    text = (
        "attribution: flipcommons-catalog\n"
        "claims:\n"
        "  - model.medieval-madness:\n"
        f"      cite: {long_url}\n"
        "      year: 1998\n"
    )
    with pytest.raises(PatchError, match="cite URL exceeds"):
        _apply(text)


def test_long_url_cite_names_source_by_hostname(
    flipcommons_catalog, kineticist_root, pm
):
    # A valid URL longer than the name column falls back to the hostname for the
    # child's name (the full URL still lands on the link, which allows more).
    url = "https://kineticist.com/" + "x" * 600
    text = (
        "attribution: flipcommons-catalog\n"
        "claims:\n"
        "  - model.medieval-madness:\n"
        f"      cite: {url}\n"
        "      year: 1998\n"
    )
    _apply(text)
    child = CitationSource.objects.get(parent=kineticist_root)
    assert child.name == "kineticist.com"
    assert child.links.get().url == url


def test_url_cite_surfaced_in_edit_history(
    client, flipcommons_catalog, kineticist_root, pm
):
    url = "https://kineticist.com/reviews/mm"
    text = (
        "attribution: flipcommons-catalog\n"
        "claims:\n"
        "  - model.medieval-madness:\n"
        "      note: per the forum\n"
        f"      cite: {url}\n"
        "      year: 1998\n"
    )
    _apply(text)

    resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
    assert resp.status_code == 200
    (cs,) = resp.json()
    year_change = next(c for c in cs["changes"] if c["field_name"] == "year")
    (citation,) = year_change["citations"]
    assert citation["source_name"] == url
    assert citation["url"] == url


def test_url_cite_with_archive_surfaces_live_link_in_edit_history(
    client, flipcommons_catalog, kineticist_root, pm
):
    # Compact field history shows the live page, NOT its Wayback snapshot — even
    # though "archive" sorts before "reference" in the default link ordering.
    url = "https://kineticist.com/reviews/mm"
    archive = "https://web.archive.org/web/20240101000000/" + url
    text = (
        "attribution: flipcommons-catalog\n"
        "claims:\n"
        "  - model.medieval-madness:\n"
        "      cite:\n"
        f"        url: {url}\n"
        f"        archive: {archive}\n"
        "      year: 1998\n"
    )
    _apply(text)

    resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
    assert resp.status_code == 200
    (cs,) = resp.json()
    year_change = next(c for c in cs["changes"] if c["field_name"] == "year")
    (citation,) = year_change["citations"]
    assert citation["url"] == url  # the live page, not the archive snapshot


# ── edit-history surfacing ─────────────────────────────────────────


def test_edit_history_exposes_citation(client, flipcommons_catalog, ipdb_root, pm):
    text = "attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n      note: per ipdb\n      cite: ipdb:4443\n      year: 1998\n"
    _apply(text)

    resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
    assert resp.status_code == 200
    body = resp.json()
    (cs,) = body
    assert cs["note"] == "per ipdb"
    year_change = next(c for c in cs["changes"] if c["field_name"] == "year")
    (citation,) = year_change["citations"]
    assert citation["source_name"] == "Internet Pinball Database #4443"
    assert citation["url"] == "https://www.ipdb.org/machine.cgi?id=4443"


def test_changeset_detail_exposes_citation(client, flipcommons_catalog, ipdb_root, pm):
    # The changeset-detail endpoint shares build_changes with edit history, so
    # its claims prefetch must also load citation instances.
    text = "attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n      cite: ipdb:4443\n      year: 1998\n"
    _apply(text)
    cs = ChangeSet.objects.get(ingest_run__isnull=False)

    resp = client.get(f"/api/pages/changesets/{cs.pk}/")
    assert resp.status_code == 200
    year_change = next(c for c in resp.json()["changes"] if c["field_name"] == "year")
    (citation,) = year_change["citations"]
    assert citation["source_name"] == "Internet Pinball Database #4443"
