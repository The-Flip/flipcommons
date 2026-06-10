"""Tests for per-entry patch ``note:`` and ``cite:`` provenance.

Covers parsing + build_plan validation, the apply-time effects (ChangeSet
note, citation source get-or-create, per-claim CitationInstance attachment),
and the documented v1 limitations (create scaffolding uncited, citation on an
unchanged claim no-ops).
"""

from __future__ import annotations

import pytest
from django.contrib.contenttypes.models import ContentType

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
from apps.provenance.models import ChangeSet, CitationInstance, Claim, Source

pytestmark = pytest.mark.django_db


@pytest.fixture
def flip_museum(db):
    # flip-museum is seeded by a provenance data migration, so get-or-create.
    source, _ = Source.objects.get_or_create(
        slug="flip-museum",
        defaults={
            "name": "Flip Museum",
            "source_type": "editorial",
            "priority": 10000,
        },
    )
    return source


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
def pm(db, flip_museum):
    return make_machine_model(
        name="Medieval Madness", slug="medieval-madness", year=1997
    )


@pytest.fixture
def prototype_tag(db):
    return Tag.objects.create(name="Prototype", slug="prototype")


def _apply(text: str, *, patch_id: str = "0001-test"):
    doc = load_patch(text)
    source = Source.objects.get(slug=doc.attribution)
    plan = build_plan(doc, source=source, patch_id=patch_id)
    return apply_plan(plan)


# ── Parsing ────────────────────────────────────────────────────────


def test_note_and_cite_parsed_and_excluded_from_fields():
    doc = load_patch(
        "attribution: flip-museum\n"
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


def test_bad_cite_format_rejected(flip_museum, pm):
    text = "attribution: flip-museum\nclaims:\n  - model.medieval-madness:\n      cite: ipdb\n      year: 1998\n"
    with pytest.raises(PatchError, match="scheme:identifier"):
        _apply(text)


def test_unknown_cite_scheme_rejected(flip_museum, pm):
    text = "attribution: flip-museum\nclaims:\n  - model.medieval-madness:\n      cite: bogus:4443\n      year: 1998\n"
    with pytest.raises(PatchError, match="unknown cite scheme"):
        _apply(text)


def test_invalid_cite_identifier_rejected(flip_museum, pm):
    # ipdb ids are digits; a non-numeric id fails normalization.
    text = "attribution: flip-museum\nclaims:\n  - model.medieval-madness:\n      cite: ipdb:not-a-number\n      year: 1998\n"
    with pytest.raises(PatchError, match="invalid ipdb identifier"):
        _apply(text)


def test_overlong_note_rejected(flip_museum, pm):
    long_note = "x" * 1001
    text = (
        "attribution: flip-museum\n"
        "claims:\n"
        "  - model.medieval-madness:\n"
        f"      note: {long_note}\n"
        "      year: 1998\n"
    )
    with pytest.raises(PatchError, match="note exceeds"):
        _apply(text)


def test_same_entity_provenance_conflict_rejected(flip_museum, pm):
    # Two entries land on one entity and one carries a note → rejected, because
    # an entity's claims collapse into a single shared changeset.
    text = """
attribution: flip-museum
claims:
  - model.medieval-madness:
      note: first reason
      year: 1998
  - model.medieval-madness:
      production_quantity: 4000
"""
    with pytest.raises(PatchError, match="combine them into one entry"):
        _apply(text)


def test_cite_on_retraction_only_entry_rejected(flip_museum, pm):
    # A cite has nothing to attach to when the entry only retracts.
    Claim.objects.assert_claim(pm, "year", 1998, source=flip_museum)
    text = "attribution: flip-museum\nclaims:\n  - model.medieval-madness:\n      cite: ipdb:4443\n      retract: [year]\n"
    with pytest.raises(PatchError, match="cite has no field to attach to"):
        _apply(text)


def test_cite_on_fieldless_create_rejected(flip_museum):
    text = "attribution: flip-museum\nclaims:\n  - manufacturer.acme:\n      create: true\n      cite: ipdb:4443\n"
    with pytest.raises(PatchError, match="cite has no field to attach to"):
        _apply(text)


def test_cite_on_empty_relationship_rejected(flip_museum, pm):
    # `tag: []` has a field key but emits zero claims, so the cite would attach
    # to nothing — a field *key* isn't a carrier.
    text = "attribution: flip-museum\nclaims:\n  - model.medieval-madness:\n      cite: ipdb:4443\n      tag: []\n"
    with pytest.raises(PatchError, match="cite has no field to attach to"):
        _apply(text)


def test_note_with_no_carrier_rejected(flip_museum, pm):
    # note: alongside only an empty relationship emits no claim/changeset, so
    # the note would silently vanish.
    text = "attribution: flip-museum\nclaims:\n  - model.medieval-madness:\n      note: this goes nowhere\n      tag: []\n"
    with pytest.raises(PatchError, match="note has nothing to attach to"):
        _apply(text)


def test_duplicate_create_rejected(flip_museum):
    # Two creates for the same ref would mint a duplicate handle; build_plan
    # rejects it as a PatchError rather than letting it surface as a ValueError
    # deep in the apply layer (which ingest_patches doesn't catch).
    text = """
attribution: flip-museum
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


def test_note_sets_changeset_note(flip_museum, pm):
    text = "attribution: flip-museum\nclaims:\n  - model.medieval-madness:\n      note: corrected per the flyer\n      year: 1998\n"
    _apply(text)
    cs = ChangeSet.objects.get(ingest_run__isnull=False)
    assert cs.note == "corrected per the flyer"


def test_retract_only_entry_lands_note(flip_museum, pm):
    # Seed a flip-museum year claim, then retract it with a note. A retraction
    # emits no assertion, so its note must still reach the changeset.
    Claim.objects.assert_claim(pm, "year", 1998, source=flip_museum)
    text = "attribution: flip-museum\nclaims:\n  - model.medieval-madness:\n      note: removing our bad year\n      retract: [year]\n"
    report = _apply(text, patch_id="0002-retract")
    assert report.retracted == 1
    cs = ChangeSet.objects.get(ingest_run__patch_id="0002-retract")
    assert cs.note == "removing our bad year"


# ── apply: cite → CitationSource + CitationInstance ────────────────


def test_cite_creates_source_and_attaches_to_claims(
    flip_museum, ipdb_root, pm, prototype_tag
):
    text = """
attribution: flip-museum
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


def test_cite_is_idempotent_across_applications(flip_museum, ipdb_root, pm):
    base = "attribution: flip-museum\nclaims:\n  - model.medieval-madness:\n      cite: ipdb:4443\n      year: {year}\n"
    _apply(base.format(year=1998), patch_id="0001-a")
    _apply(base.format(year=1999), patch_id="0002-b")
    # Re-citing the same id reuses the one child source.
    assert (
        CitationSource.objects.filter(parent=ipdb_root, identifier="4443").count() == 1
    )


def test_create_scaffolding_not_cited(flip_museum, ipdb_root):
    # A create entry's authored field (name) is cited; the adapter-owned slug
    # and status claims are not.
    text = """
attribution: flip-museum
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


def test_cite_on_unchanged_value_noops(flip_museum, ipdb_root, pm):
    # An already-correct, same-source value diffs as unchanged, so adding a
    # cite: writes no new claim and attaches no citation (documented v1 limit).
    Claim.objects.assert_claim(pm, "year", 2000, source=flip_museum)
    text = "attribution: flip-museum\nclaims:\n  - model.medieval-madness:\n      cite: ipdb:4443\n      year: 2000\n"
    _apply(text)
    year_claim = pm.claims.get(field_name="year", is_active=True, source=flip_museum)
    assert not year_claim.citation_instances.exists()
    assert not CitationInstance.objects.exists()


def test_note_on_unchanged_value_noops(flip_museum, pm):
    # Same root cause as the cite no-op: an entry that re-asserts an
    # already-active same-source value diffs as unchanged, so no ChangeSet is
    # created and the note is silently dropped (documented v1 limit). Build
    # time can't catch this — it depends on the post-diff result.
    Claim.objects.assert_claim(pm, "year", 2000, source=flip_museum)
    text = "attribution: flip-museum\nclaims:\n  - model.medieval-madness:\n      note: confirmed correct\n      year: 2000\n"
    report = _apply(text)
    assert report.asserted == 0  # nothing written
    assert not ChangeSet.objects.filter(ingest_run__isnull=False).exists()


def test_attach_citations_is_per_claim(flip_museum, ipdb_root, pm):
    # Direct IngestPlan: two assertions on one entity, only one carries a
    # citation_ref. The citation must ride only that claim — never bleed onto
    # the other claim that merely shares the entity.
    ct = ContentType.objects.get_for_model(MachineModel)
    plan = IngestPlan(
        source=flip_museum, input_fingerprint="fp", patch_id="0001-direct"
    )
    plan.assertions.append(
        PlannedClaimAssert(
            field_name="year",
            value=1998,
            content_type_id=ct.pk,
            object_id=pm.pk,
            citation_ref=CitationRef("ipdb", "4443"),
        )
    )
    plan.assertions.append(
        PlannedClaimAssert(
            field_name="production_quantity",
            value=4000,
            content_type_id=ct.pk,
            object_id=pm.pk,
        )
    )
    apply_plan(plan)

    year_claim = pm.claims.get(field_name="year", is_active=True)
    qty_claim = pm.claims.get(field_name="production_quantity", is_active=True)
    assert year_claim.citation_instances.exists()
    assert not qty_claim.citation_instances.exists()


def test_missing_citation_root_errors(flip_museum, pm):
    # No ipdb root seeded → a clear error, not a silent miss.
    text = "attribution: flip-museum\nclaims:\n  - model.medieval-madness:\n      cite: ipdb:4443\n      year: 1998\n"
    with pytest.raises(CitationSource.DoesNotExist, match="No root CitationSource"):
        _apply(text)


# ── cite: URL form → web CitationSource nested under a root ────────


def test_url_cite_without_matching_root_errors(flip_museum, pm):
    # A URL whose domain matches no seeded website root is rejected — a patch
    # must nest evidence under a curated root, not mint a parentless (abstract)
    # web source. The author seeds the root in an earlier patch first.
    url = "https://pinside.com/pinball/forum/topic/mm-prototype"
    text = (
        "attribution: flip-museum\n"
        "claims:\n"
        "  - model.medieval-madness:\n"
        f"      cite: {url}\n"
        "      year: 1998\n"
    )
    with pytest.raises(CitationSource.DoesNotExist, match="No website .*root"):
        _apply(text)


def test_url_cite_reuses_preexisting_source(flip_museum, pm):
    # A source a curator already linked to this exact URL is reused, not
    # duplicated.
    url = "https://example.com/evidence"
    existing = CitationSource.objects.create(name="Curated", source_type="web")
    existing.links.create(link_type="reference", url=url)
    text = (
        "attribution: flip-museum\n"
        "claims:\n"
        "  - model.medieval-madness:\n"
        f"      cite: {url}\n"
        "      year: 1998\n"
    )
    _apply(text)
    year_claim = pm.claims.get(field_name="year", is_active=True)
    assert year_claim.citation_instances.get().citation_source_id == existing.pk
    assert CitationSource.objects.filter(links__url=url).distinct().count() == 1


def test_url_cite_nests_under_domain_matched_root(flip_museum, kineticist_root, pm):
    # A URL whose domain matches a seeded root becomes a child under that root,
    # not a flat parentless orphan.
    url = "https://kineticist.com/reviews/medieval-madness"
    text = (
        "attribution: flip-museum\n"
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


def test_url_cite_under_root_dedups_and_separates(flip_museum, kineticist_root, pm):
    # Same URL twice → one child; a different path on the same domain → a second
    # child under the same root.
    base = (
        "attribution: flip-museum\n"
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


def test_ipdb_url_cite_rejected(flip_museum, pm):
    # A known-scheme record URL must be cited via scheme:identifier so it dedups.
    text = (
        "attribution: flip-museum\n"
        "claims:\n"
        "  - model.medieval-madness:\n"
        "      cite: https://www.ipdb.org/machine.cgi?id=4443\n"
        "      year: 1998\n"
    )
    with pytest.raises(PatchError, match="matches the ipdb scheme.*ipdb:4443"):
        _apply(text)


def test_opdb_url_cite_rejected(flip_museum, pm):
    text = (
        "attribution: flip-museum\n"
        "claims:\n"
        "  - model.medieval-madness:\n"
        "      cite: https://opdb.org/machines/GRhX5\n"
        "      year: 1998\n"
    )
    with pytest.raises(PatchError, match="matches the opdb scheme"):
        _apply(text)


def test_malformed_url_cite_rejected(flip_museum, pm):
    text = (
        "attribution: flip-museum\n"
        "claims:\n"
        "  - model.medieval-madness:\n"
        "      cite: https://\n"
        "      year: 1998\n"
    )
    with pytest.raises(PatchError, match="is not a valid URL"):
        _apply(text)


def test_overlong_url_cite_rejected(flip_museum, pm):
    long_url = "https://example.com/" + "x" * 2000
    text = (
        "attribution: flip-museum\n"
        "claims:\n"
        "  - model.medieval-madness:\n"
        f"      cite: {long_url}\n"
        "      year: 1998\n"
    )
    with pytest.raises(PatchError, match="cite URL exceeds"):
        _apply(text)


def test_long_url_cite_names_source_by_hostname(flip_museum, kineticist_root, pm):
    # A valid URL longer than the name column falls back to the hostname for the
    # child's name (the full URL still lands on the link, which allows more).
    url = "https://kineticist.com/" + "x" * 600
    text = (
        "attribution: flip-museum\n"
        "claims:\n"
        "  - model.medieval-madness:\n"
        f"      cite: {url}\n"
        "      year: 1998\n"
    )
    _apply(text)
    child = CitationSource.objects.get(parent=kineticist_root)
    assert child.name == "kineticist.com"
    assert child.links.get().url == url


def test_url_cite_surfaced_in_edit_history(client, flip_museum, kineticist_root, pm):
    url = "https://kineticist.com/reviews/mm"
    text = (
        "attribution: flip-museum\n"
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


# ── edit-history surfacing ─────────────────────────────────────────


def test_edit_history_exposes_citation(client, flip_museum, ipdb_root, pm):
    text = "attribution: flip-museum\nclaims:\n  - model.medieval-madness:\n      note: per ipdb\n      cite: ipdb:4443\n      year: 1998\n"
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


def test_changeset_detail_exposes_citation(client, flip_museum, ipdb_root, pm):
    # The changeset-detail endpoint shares build_changes with edit history, so
    # its claims prefetch must also load citation instances.
    text = "attribution: flip-museum\nclaims:\n  - model.medieval-madness:\n      cite: ipdb:4443\n      year: 1998\n"
    _apply(text)
    cs = ChangeSet.objects.get(ingest_run__isnull=False)

    resp = client.get(f"/api/pages/changesets/{cs.pk}/")
    assert resp.status_code == 200
    year_change = next(c for c in resp.json()["changes"] if c["field_name"] == "year")
    (citation,) = year_change["citations"]
    assert citation["source_name"] == "Internet Pinball Database #4443"
