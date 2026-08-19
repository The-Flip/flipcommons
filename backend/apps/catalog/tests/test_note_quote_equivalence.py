"""The note-quote backfill's equivalence oracle and migration behavior.

The oracle: ``rewrite-then-ingest ≡ ingest-then-migrate``. A patch whose
quote was moved onto the ``cite:`` mapping at the source (flippatch's rewrite
script) and a patch ingested in its legacy ``note:``-scaffolding form and then
run through the backfill migrations must reach the **identical** end state —
same quote on the instance, same residual note. This is the property that
catches any divergence between the two consumers of the recognizer (the
rewrite script in flippatch, the migrations here), including a drift between
the two byte-identical recognizer copies.

The migration halves are exercised through their real ``_forward`` functions
(imported via ``importlib`` — migration module names start with a digit).
"""

from __future__ import annotations

from importlib import import_module

import pytest
from django.apps import apps as django_apps

from apps.catalog.tests.conftest import make_machine_model
from apps.claim_ingest.apply import apply_plan
from apps.claim_ingest.patches import build_plan, load_patch
from apps.provenance.models import ChangeSet, Source

_populate = import_module("apps.provenance.migrations.0023_populate_citation_quotes")
_strip = import_module("apps.provenance.migrations.0024_strip_note_quote_scaffolding")

pytestmark = pytest.mark.django_db


@pytest.fixture
def models(db, flipcommons_catalog):
    return {
        "legacy": make_machine_model(
            name="Legacy MM", slug="legacy-mm", production_year=1997
        ),
        "rewritten": make_machine_model(
            name="Rewritten MM", slug="rewritten-mm", production_year=1997
        ),
    }


def _apply(text: str, *, patch_id: str) -> None:
    doc = load_patch(text)
    source = Source.objects.get(slug=doc.attribution)
    plan = build_plan(doc, source=source, patch_id=patch_id)
    apply_plan(plan)


def _run_backfill() -> None:
    _populate._forward(django_apps, None)
    _strip._forward(django_apps, None)


def _year_changeset(model) -> ChangeSet:
    claim = model.claims.get(field_name="production_year", is_active=True)
    changeset = claim.changeset
    assert isinstance(changeset, ChangeSet)
    return changeset


def _evidence(model) -> set[tuple[str, str, str]]:
    claim = model.claims.get(field_name="production_year", is_active=True)
    return {
        (inst.citation_source.name, inst.locator, inst.quote)
        for inst in claim.citation_instances.select_related("citation_source")
    }


class TestEquivalenceOracle:
    def test_pure_quote_note(self, models, ipdb_root):
        # Legacy path: the note carries the quote as scaffolding.
        _apply(
            "attribution: flipcommons-catalog\n"
            "claims:\n"
            "  - model.legacy-mm:\n"
            "      note: 'IPDB says \"This game was never produced\".'\n"
            "      cite: ipdb:4443\n"
            "      production_year: 1998\n",
            patch_id="0001-legacy",
        )
        # Rewritten path: what flippatch's rewrite script emits for that note.
        _apply(
            "attribution: flipcommons-catalog\n"
            "claims:\n"
            "  - model.rewritten-mm:\n"
            "      cite:\n"
            "        ref: ipdb:4443\n"
            "        quote: 'This game was never produced'\n"
            "      production_year: 1998\n",
            patch_id="0002-rewritten",
        )

        _run_backfill()

        assert _year_changeset(models["legacy"]).note == ""
        assert _year_changeset(models["rewritten"]).note == ""
        assert _evidence(models["legacy"]) == _evidence(models["rewritten"])
        assert _evidence(models["legacy"]) == {
            ("Internet Pinball Database #4443", "", "This game was never produced")
        }

    def test_mixed_note_keeps_residual(self, models, ipdb_root):
        _apply(
            "attribution: flipcommons-catalog\n"
            "claims:\n"
            "  - model.legacy-mm:\n"
            "      note: 'IPDB says \"This is a re-themed game.\"; IPDB records 1 unit.'\n"
            "      cite: ipdb:4443\n"
            "      production_year: 1998\n",
            patch_id="0001-legacy",
        )
        _apply(
            "attribution: flipcommons-catalog\n"
            "claims:\n"
            "  - model.rewritten-mm:\n"
            "      note: 'IPDB records 1 unit.'\n"
            "      cite:\n"
            "        ref: ipdb:4443\n"
            "        quote: 'This is a re-themed game.'\n"
            "      production_year: 1998\n",
            patch_id="0002-rewritten",
        )

        _run_backfill()

        assert _year_changeset(models["legacy"]).note == "IPDB records 1 unit."
        assert _year_changeset(models["rewritten"]).note == "IPDB records 1 unit."
        assert _evidence(models["legacy"]) == _evidence(models["rewritten"])

    def test_unrecognized_note_is_untouched_on_both_paths(self, models, ipdb_root):
        # The rewrite script skips what the recognizer refuses, so the
        # "rewritten" file carries the identical note — and the migration
        # must leave the ingested row equally alone.
        note = (
            'note: \'The name includes "Prototype", which indicates that this '
            "is a prototype that never reached commercial production.'\n"
        )
        _apply(
            "attribution: flipcommons-catalog\n"
            "claims:\n"
            "  - model.legacy-mm:\n"
            f"      {note}"
            "      cite: ipdb:4443\n"
            "      production_year: 1998\n",
            patch_id="0001-legacy",
        )
        _apply(
            "attribution: flipcommons-catalog\n"
            "claims:\n"
            "  - model.rewritten-mm:\n"
            f"      {note}"
            "      cite: ipdb:4443\n"
            "      production_year: 1998\n",
            patch_id="0002-rewritten",
        )

        _run_backfill()

        expected = (
            'The name includes "Prototype", which indicates that this is a '
            "prototype that never reached commercial production."
        )
        assert _year_changeset(models["legacy"]).note == expected
        assert _year_changeset(models["rewritten"]).note == expected
        assert _evidence(models["legacy"]) == _evidence(models["rewritten"])
        assert all(quote == "" for _, _, quote in _evidence(models["legacy"]))


class TestBackfillMigration:
    def test_multi_claim_changeset_shares_the_quote(self, models, ipdb_root):
        _apply(
            "attribution: flipcommons-catalog\n"
            "claims:\n"
            "  - model.legacy-mm:\n"
            "      note: 'IPDB says \"never produced\".'\n"
            "      cite: ipdb:4443\n"
            "      production_year: 1998\n"
            "      production_quantity: 4000\n",
            patch_id="0001-legacy",
        )
        _run_backfill()

        year = models["legacy"].claims.get(field_name="production_year", is_active=True)
        qty = models["legacy"].claims.get(
            field_name="production_quantity", is_active=True
        )
        year_inst = year.citation_instances.get()
        assert year_inst.quote == "never produced"
        assert qty.citation_instances.get().pk == year_inst.pk

    def test_quote_note_without_citation_reported_not_migrated(
        self, models, flipcommons_catalog, capsys
    ):
        from apps.provenance.test_factories import make_claim, source_changeset

        changeset = source_changeset(flipcommons_catalog)
        changeset.note = 'IPDB says "never produced".'
        changeset.save(update_fields=["note"])
        make_claim(models["legacy"], "production_year", 1998, changeset=changeset)

        _run_backfill()

        changeset.refresh_from_db()
        assert changeset.note == 'IPDB says "never produced".'  # untouched
        assert "no citation instances" in capsys.readouterr().out

    def test_seed_import_notes_blanked(self, models, flipcommons_catalog):
        from apps.provenance.test_factories import make_claim, source_changeset

        changeset = source_changeset(flipcommons_catalog)
        changeset.note = "Seed import (backfilled)."
        changeset.save(update_fields=["note"])
        make_claim(models["legacy"], "production_year", 1998, changeset=changeset)

        _run_backfill()

        changeset.refresh_from_db()
        assert changeset.note == ""

    def test_populate_reverse_blanks_only_migrated_quotes(self, models, ipdb_root):
        _apply(
            "attribution: flipcommons-catalog\n"
            "claims:\n"
            "  - model.legacy-mm:\n"
            "      note: 'IPDB says \"never produced\".'\n"
            "      cite: ipdb:4443\n"
            "      production_year: 1998\n",
            patch_id="0001-legacy",
        )
        _apply(
            "attribution: flipcommons-catalog\n"
            "claims:\n"
            "  - model.rewritten-mm:\n"
            "      cite:\n"
            "        ref: ipdb:4443\n"
            "        quote: 'authored at ingest'\n"
            "      production_year: 1998\n",
            patch_id="0002-rewritten",
        )
        _populate._forward(django_apps, None)
        assert _evidence(models["legacy"]) != set()

        _populate._reverse(django_apps, None)

        # The migrated quote is blanked; the ingest-authored one survives.
        assert {q for _, _, q in _evidence(models["legacy"])} == {""}
        assert {q for _, _, q in _evidence(models["rewritten"])} == {
            "authored at ingest"
        }
