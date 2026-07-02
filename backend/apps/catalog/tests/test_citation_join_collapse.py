"""Characterization: the 0018 collapse dedups the real clone fan-out.

Drives the live ingest apply path (not literal patch files) to reproduce the
shape the write path actually mints -- one ``CitationInstance`` clone per edited
field of a single ``cite:`` -- then runs the backfill/collapse migration forward
and locks the dedup: N clones -> one shared instance, every claim's join row
repointed to it.

Transitional. It builds through the EXP2 clone-per-claim write path and reads
``CitationInstance.claim`` directly, both of which CON1/CON2 rework -- revise or
retire it there.
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps as django_apps

from apps.catalog.tests.conftest import make_machine_model
from apps.claim_ingest.patches import build_plan, load_patch
from apps.provenance.models import (
    CitationInstance,
    ClaimCitationInstance,
    Source,
)

_migration = importlib.import_module(
    "apps.provenance.migrations.0018_backfill_scalar_citation_joins"
)

pytestmark = pytest.mark.django_db


def _apply(text: str, *, patch_id: str = "0001-test"):
    from apps.claim_ingest.apply import apply_plan

    doc = load_patch(text)
    source = Source.objects.get(slug=doc.attribution)
    return apply_plan(build_plan(doc, source=source, patch_id=patch_id))


def test_collapse_dedups_multi_field_single_cite(flipcommons_catalog, ipdb_root):
    pm = make_machine_model(name="Medieval Madness", slug="medieval-madness", year=1997)
    # One entry, one cite, two edited scalar fields -> two identical clones.
    _apply(
        "attribution: flipcommons-catalog\n"
        "claims:\n"
        "  - model.medieval-madness:\n"
        "      cite: ipdb:4443\n"
        "      year: 1998\n"
        "      player_count: 4\n"
    )

    year_claim = pm.claims.get(field_name="year", is_active=True)
    player_claim = pm.claims.get(field_name="player_count", is_active=True)

    # EXP2 shape: a distinct clone per field, same source + locator, each with
    # its own join row.
    year_inst = year_claim.citation_instances.get()
    player_inst = player_claim.citation_instances.get()
    assert year_inst.pk != player_inst.pk
    assert year_inst.citation_source_id == player_inst.citation_source_id
    assert year_inst.locator == player_inst.locator == ""
    assert (
        ClaimCitationInstance.objects.filter(
            citation_instance__in=[year_inst, player_inst]
        ).count()
        == 2
    )

    _migration._forward(django_apps, None)

    # One shared instance survives; both claims reach it through the join.
    survivors = CitationInstance.objects.filter(claim__isnull=False)
    assert survivors.count() == 1
    survivor = survivors.get()
    linked_claims = set(
        ClaimCitationInstance.objects.filter(citation_instance=survivor).values_list(
            "claim_id", flat=True
        )
    )
    assert linked_claims == {year_claim.pk, player_claim.pk}
