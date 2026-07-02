"""Strip migrated quote-notes to their residual; blank seed-import boilerplate.

Step two of the note-quote backfill (docs/plans/citations/
CitationInstanceQuotes.md): with the quotes verifiably on their
``CitationInstance`` rows (``0023``), the ``<source> says "…"`` scaffolding
comes off the notes. A pure-quote note blanks; a mixed note keeps its
editorial residual. The strip is what makes the equivalence oracle hold — a
rewritten-then-ingested patch yields an empty note, so the migrated
historical note must reach the same state.

Self-verifying: a note is stripped only when every one of its changeset's
field-level instances carries exactly the extracted quote — i.e. only where
``0023`` (or an ingest of the rewritten patch) actually landed it. Anything
else is left untouched and reported.

Also blanks the ~16,834 ``Seed import (backfilled).`` notes —
``provenance/0011`` backfill boilerplate, redundant with the changeset's
ingest-run linkage. The recognizer never sees them (not quote-shaped); they
go by exact-match update.

Reverse is a no-op: the original scaffolding is not reconstructible (nor
meant to be — both migrations land before public launch, while the entire
corpus is still Flipcommons-authored bootstrapping data).
"""

from __future__ import annotations

from django.db import migrations

from apps.provenance.note_quote_backfill import SEED_NOTE, quote_candidates


def _forward(apps, schema_editor):
    ChangeSet = apps.get_model("provenance", "ChangeSet")

    stripped = 0
    for candidate in quote_candidates(apps):
        if candidate.reason is not None or candidate.instances is None:
            continue
        assert candidate.extracted is not None
        if any(
            inst.quote != candidate.extracted.quote for inst in candidate.instances
        ):
            print(
                f"  SKIP changeset {candidate.changeset.pk}: quote not populated: "
                f"{candidate.changeset.note[:80]}"
            )
            continue
        ChangeSet.objects.filter(pk=candidate.changeset.pk).update(
            note=candidate.extracted.residual
        )
        stripped += 1

    seed = ChangeSet.objects.filter(note=SEED_NOTE).update(note="")
    print(f"\n  stripped {stripped} quote-notes; blanked {seed} seed-import notes")


class Migration(migrations.Migration):
    dependencies = [
        ("provenance", "0023_populate_citation_quotes"),
    ]

    operations = [
        migrations.RunPython(_forward, migrations.RunPython.noop),
    ]
