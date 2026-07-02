"""Tests for inline-cited patch descriptions.

A patch may carry rich markdown descriptions whose facts are backed by inline
``[[cite:<handle>]]`` footnotes. A *new* footnote uses a numeric handle declared
in a ``cites:`` map (minted to a floating CitationInstance at apply time,
reached only by its marker); an *existing* footnote uses the instance's durable slug and needs no
``cites:`` entry (it self-resolves through standard conversion). Covers parse +
correspondence guards, apply-time minting + marker rewrite, the re-edit
round-trip, and the new-cite dry-run carve-out.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.catalog.models import Manufacturer
from apps.catalog.tests.conftest import make_machine_model
from apps.citation.models import CitationInstance
from apps.claim_ingest.apply import apply_plan
from apps.claim_ingest.patches import PatchError, build_plan, load_patch
from apps.core.markdown import (
    convert_storage_to_authoring,
    render_all_links,
)
from apps.provenance.models import Source

pytestmark = pytest.mark.django_db


@pytest.fixture
def pm(db, flipcommons_catalog):
    return make_machine_model(
        name="Medieval Madness", slug="medieval-madness", year=1997
    )


def _apply(text: str, *, patch_id: str = "0001-test", dry_run: bool = False):
    doc = load_patch(text)
    source = Source.objects.get(slug=doc.attribution)
    plan = build_plan(doc, source=source, patch_id=patch_id)
    return apply_plan(plan, dry_run=dry_run)


def _floating():
    """Floating (inline) CitationInstances — reached only by their markers,
    so they carry no ClaimCitationInstance join rows."""
    return CitationInstance.objects.filter(claim_links__isnull=True)


def _is_slug(value: str) -> bool:
    # CitationInstance slugs are exactly 8 lowercase consonants.
    return len(value) == 8 and value.isalpha() and value.islower()


def _description_value(entity) -> str:
    value = entity.claims.get(field_name="description", is_active=True).value
    assert isinstance(value, str)
    return value


# ── apply: new inline citations mint + rewrite ─────────────────────


def test_two_new_handles_mint_two_floating_instances(
    flipcommons_catalog, ipdb_root, kineticist_root, pm
):
    text = """
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      description: "A solid-state classic.[[cite:1]] Few survive.[[cite:2]]"
      cites:
        '1': ipdb:4443
        '2': https://kineticist.com/mm
"""
    _apply(text)

    instances = list(_floating())
    assert len(instances) == 2
    assert all(_is_slug(ci.slug) for ci in instances)
    # Inline cites stay marker-native: each minted instance is reached only by
    # its marker, never through the scalar join. Assert per-instance rather than a
    # global count so a fixture adding an unrelated scalar cite can't mask it.
    assert all(ci.claim_links.exists() is False for ci in instances)
    # One per source — scheme dedups through ipdb, the URL through kineticist.
    source_ids = {ci.citation_source_id for ci in instances}
    assert len(source_ids) == 2

    stored = _description_value(pm)
    pks = sorted(ci.pk for ci in instances)
    for pk in pks:
        assert f"[[cite:id:{pk}]]" in stored
    assert "[[cite:1]]" not in stored
    assert "[[cite:2]]" not in stored

    html = render_all_links(stored)
    assert 'data-cite-index="1"' in html
    assert 'data-cite-index="2"' in html
    assert "[[cite:" not in html


def test_same_new_handle_twice_one_instance_same_pk(flipcommons_catalog, ipdb_root, pm):
    text = """
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      description: "First mention.[[cite:1]] Second mention.[[cite:1]]"
      cites:
        '1': ipdb:4443
"""
    _apply(text)

    (ci,) = list(_floating())
    stored = _description_value(pm)
    # Both markers resolve to the single minted instance's pk.
    assert stored.count(f"[[cite:id:{ci.pk}]]") == 2


def test_inline_cite_on_create_entity(flipcommons_catalog, ipdb_root):
    # A same-patch create: the description assertion targets a handle, resolved
    # by _patch_handles before _materialize_inline_citations rewrites it.
    text = """
attribution: flipcommons-catalog
claims:
  - manufacturer.mazatron:
      create: true
      name: Mazatron
      description: "Founded 1990.[[cite:1]]"
      cites:
        '1': ipdb:4443
"""
    _apply(text)

    mfr = Manufacturer.objects.get(slug="mazatron")
    (ci,) = list(_floating())
    assert _is_slug(ci.slug)
    assert f"[[cite:id:{ci.pk}]]" in _description_value(mfr)


def test_inline_cite_minted_sources_attributed_to_patch_actor(
    flipcommons_catalog, ipdb_root, kineticist_root, pm
):
    """A cite: that mints a new citation source attributes it to the patch's
    Source actor — both the scheme path (ipdb child) and the web path
    (kineticist child) — closing the gap for inline cites as for `sources:`."""
    text = """
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      description: "Scheme.[[cite:1]] Web.[[cite:2]]"
      cites:
        '1': ipdb:4443
        '2': https://kineticist.com/mm
"""
    _apply(text)

    actor = Source.objects.get(slug="flipcommons-catalog").actor
    minted = list(_floating())
    assert len(minted) == 2
    for ci in minted:
        child = ci.citation_source
        assert child.created_by == actor, child
        assert child.updated_by == actor, child


def test_url_archive_spec_backfills_archive_link(
    flipcommons_catalog, kineticist_root, pm
):
    text = """
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      description: "Archived fact.[[cite:1]]"
      cites:
        '1':
          url: https://kineticist.com/mm
          archive: https://web.archive.org/web/2020/https://kineticist.com/mm
"""
    _apply(text)

    (ci,) = list(_floating())
    urls = set(ci.citation_source.links.values_list("url", flat=True))
    assert "https://kineticist.com/mm" in urls
    assert "https://web.archive.org/web/2020/https://kineticist.com/mm" in urls


def test_malformed_cite_url_surfaces_validation_error(
    flipcommons_catalog, kineticist_root, pm
):
    # A malformed cite URL must propagate out of apply_plan as a ValidationError
    # — the type the patch runner maps to a per-patch PatchError. Pins the ingest
    # error contract so a future leaf change (raising a different exception type)
    # can't silently regress it to an uninformative traceback. The wrapped error
    # must name the offending URL so the PatchError can point at the line.
    text = """
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      description: "Bad cite.[[cite:1]]"
      cites:
        '1':
          url: "https://kineticist.com/m m"
"""
    with pytest.raises(ValidationError) as exc_info:
        _apply(text)
    assert "https://kineticist.com/m m" in "; ".join(exc_info.value.messages)


def test_malformed_cite_archive_url_names_the_archive(
    flipcommons_catalog, kineticist_root, pm
):
    # The page URL is valid and resolves under the kineticist root; the *archive*
    # URL passes the parser's loose check (http(s):// + host + length) but fails
    # Django's URLField in get_or_create_web_source's separate archive-link
    # full_clean. The wrapped error must name the archive URL — naming only the
    # (valid) page URL would point an author at the wrong line.
    text = """
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      description: "Archived fact.[[cite:1]]"
      cites:
        '1':
          url: https://kineticist.com/mm
          archive: "https://web.archive.org/web/2020/https://kineticist.com/m m"
"""
    with pytest.raises(ValidationError) as exc_info:
        _apply(text)
    assert "https://web.archive.org/web/2020/https://kineticist.com/m m" in "; ".join(
        exc_info.value.messages
    )


def test_unknown_web_root_cite_surfaces_validation_error(flipcommons_catalog, pm):
    # A well-formed cite URL whose domain matches no seeded root: the web
    # resolver raises CitationSource.DoesNotExist, which the runner's except
    # would NOT catch on its own (only ValidationError) — pre-fix it surfaced as
    # a raw traceback. The resolver wrap re-raises an enriched ValidationError
    # naming the URL, so it reaches _apply_one as a clean per-patch failure.
    text = """
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      description: "Cite under no root.[[cite:1]]"
      cites:
        '1':
          url: "https://no-such-domain.example/page"
"""
    with pytest.raises(ValidationError) as exc_info:
        _apply(text)
    assert "https://no-such-domain.example/page" in "; ".join(exc_info.value.messages)


def test_unknown_scheme_root_cite_surfaces_validation_error(flipcommons_catalog, pm):
    # The scheme analog: a valid ipdb cite with no ipdb root seeded. The scheme
    # resolver raises CitationSource.DoesNotExist (likewise outside the runner's
    # bare except). The wrap re-raises a ValidationError naming scheme:identifier.
    text = """
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      description: "Cite a scheme with no root.[[cite:1]]"
      cites:
        '1': ipdb:4443
"""
    with pytest.raises(ValidationError) as exc_info:
        _apply(text)
    assert "ipdb:4443" in "; ".join(exc_info.value.messages)


def test_two_inline_cited_edits_same_entity_rejected(
    flipcommons_catalog, ipdb_root, pm
):
    # Two entries editing the same entity's description, each with inline cites:
    # _build_claims keeps only the last (last-write-wins), so minting per entry
    # would orphan the discarded entry's floating instance. Inline cites are
    # provenance, so this trips the multi-entry guard at build time, before any
    # mint — combine them into one entry, like note/cite.
    text = """
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      description: "First take.[[cite:1]]"
      cites:
        '1': ipdb:4443
  - model.medieval-madness:
      description: "Second take.[[cite:1]]"
      cites:
        '1': ipdb:5555
"""
    with pytest.raises(PatchError, match="combine them into one entry"):
        _apply(text)
    assert _floating().count() == 0  # rejected before apply — nothing minted


def test_out_of_order_noncontiguous_handles_accepted(
    flipcommons_catalog, ipdb_root, kineticist_root, pm
):
    # Handles need no ordering or contiguity: '5' and '2', markers reversed.
    text = """
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      description: "Later fact.[[cite:5]] Earlier fact.[[cite:2]]"
      cites:
        '5': ipdb:4443
        '2': https://kineticist.com/mm
"""
    _apply(text)
    assert _floating().count() == 2


# ── re-edit round-trip (existing slugs) ────────────────────────────


def test_reedit_with_existing_slug_no_mint_no_churn(flipcommons_catalog, ipdb_root, pm):
    _apply(
        "attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n"
        '      description: "A fact.[[cite:1]]"\n      cites:\n        '
        "'1': ipdb:4443\n"
    )
    (ci,) = list(_floating())
    authoring = convert_storage_to_authoring(_description_value(pm))
    assert f"[[cite:{ci.slug}]]" in authoring  # rehydrated to the durable slug

    # Resubmit the rehydrated text verbatim, no cites: — byte-identical storage.
    report = _apply(
        f"attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n"
        f'      description: "{authoring}"\n',
        patch_id="0002-reedit",
    )
    assert _floating().count() == 1  # no new mint — slug reused
    assert report.asserted == 0
    assert report.unchanged == 1

    # Reword one sentence, keep the slug marker — only the text diffs.
    reworded = authoring.replace("A fact.", "A reworded fact.")
    report = _apply(
        f"attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n"
        f'      description: "{reworded}"\n',
        patch_id="0003-reword",
    )
    assert _floating().count() == 1  # still no new mint
    assert report.asserted == 1
    assert report.superseded == 1
    assert f"[[cite:id:{ci.pk}]]" in _description_value(pm)


def test_unknown_existing_slug_rejected_at_conversion(flipcommons_catalog, pm):
    # A slug-grammar marker with no backing passes the lexical classifier but
    # fails downstream in convert_authoring_to_storage ("Cite not found").
    text = (
        "attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n"
        '      description: "Bad.[[cite:zzzzzzzz]]"\n'
    )
    with pytest.raises(ValidationError):
        _apply(text)


# ── correspondence / grammar guards (PatchError, DB-free) ──────────


def test_numeric_handle_without_cites_entry_rejected(flipcommons_catalog, pm):
    text = (
        "attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n"
        '      description: "Fact.[[cite:1]]"\n'
    )
    with pytest.raises(PatchError, match="no 'cites:' entry to mint from"):
        _apply(text)


def test_unused_cites_entry_rejected(flipcommons_catalog, ipdb_root, pm):
    text = """
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      description: "Fact.[[cite:1]]"
      cites:
        '1': ipdb:4443
        '2': ipdb:5555
"""
    with pytest.raises(PatchError, match="not referenced"):
        _apply(text)


def test_slug_keyed_cites_entry_rejected(flipcommons_catalog, ipdb_root, pm):
    text = """
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      description: "Fact.[[cite:bqntvkrs]]"
      cites:
        bqntvkrs: ipdb:4443
"""
    with pytest.raises(PatchError, match="must be numeric handles"):
        _apply(text)


def test_cites_without_markdown_claim_rejected(flipcommons_catalog, ipdb_root, pm):
    # year is not a markdown field — nothing for the cite to bind to.
    text = """
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      year: 1998
      cites:
        '1': ipdb:4443
"""
    with pytest.raises(PatchError, match="requires a markdown-field claim"):
        _apply(text)


def test_cites_on_delete_entry_rejected(flipcommons_catalog, ipdb_root, pm):
    text = """
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      delete: true
      cites:
        '1': ipdb:4443
"""
    with pytest.raises(PatchError, match="requires a markdown-field claim"):
        _apply(text)


# ── raw-pk / malformed-handle guard ────────────────────────────────


@pytest.mark.parametrize("handle", ["id:1", "1a", "Foo"])
def test_malformed_inline_handle_rejected(flipcommons_catalog, pm, handle):
    # The load-bearing case is [[cite:id:1]]: without the strict grammar it would
    # classify as a slug and store verbatim, reopening the raw-pk hole.
    text = (
        "attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n"
        f'      description: "X.[[cite:{handle}]]"\n'
    )
    with pytest.raises(PatchError, match="malformed inline citation"):
        _apply(text)


def test_unquoted_integer_handle_is_parse_error(flipcommons_catalog, pm):
    # A bare integer YAML key is rejected by the strict loader before the adapter
    # runs (patchkit and hand-authors must quote handles).
    text = """
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      description: "Fact.[[cite:1]]"
      cites:
        1: ipdb:4443
"""
    with pytest.raises(PatchError, match="non-string mapping key"):
        _apply(text)


# ── dry-run carve-out ──────────────────────────────────────────────


def test_dry_run_new_cite_edit_does_not_raise(flipcommons_catalog, ipdb_root, pm):
    text = """
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      description: "Fact.[[cite:1]]"
      cites:
        '1': ipdb:4443
"""
    report = _apply(text, dry_run=True)
    assert not report.errors
    assert report.asserted == 1
    assert _floating().count() == 0  # nothing minted in dry-run


def test_dry_run_new_cite_create_does_not_raise(flipcommons_catalog, ipdb_root):
    text = """
attribution: flipcommons-catalog
claims:
  - manufacturer.mazatron:
      create: true
      name: Mazatron
      description: "Founded 1990.[[cite:1]]"
      cites:
        '1': ipdb:4443
"""
    report = _apply(text, dry_run=True)
    assert not report.errors
    assert not Manufacturer.objects.filter(slug="mazatron").exists()


def test_dry_run_existing_slug_validates_normally(flipcommons_catalog, ipdb_root, pm):
    # Mint a real cite, then dry-run a re-edit using its slug (no cites:): the
    # slug resolves against the DB, so it stays on the standard validate path.
    _apply(
        "attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n"
        '      description: "A fact.[[cite:1]]"\n      cites:\n        '
        "'1': ipdb:4443\n"
    )
    authoring = convert_storage_to_authoring(_description_value(pm))
    report = _apply(
        f"attribution: flipcommons-catalog\nclaims:\n  - model.medieval-madness:\n"
        f'      description: "{authoring}"\n',
        patch_id="0002-dry",
        dry_run=True,
    )
    assert not report.errors
