"""Populate ``CitationInstance.quote`` from quote-shaped ``ChangeSet.note``s.

Step one of the two-migration note-quote backfill (docs/plans/citations/
CitationInstanceQuotes.md): write the quotes, don't touch the notes. The strip
(``0024``) blanks the migrated notes to their residual only where this
migration verifiably landed the quote, so the two are safe to review between.

For each changeset whose note the recognizer matches, the quote lands on the
changeset's field-level instances via the ``ClaimCitationInstance`` join —
inline description instances carry no join rows, so they're naturally
excluded. An instance is shared only within a changeset (verified: no instance
spans two changesets), so the write is unambiguous; the walk in
``note_quote_backfill`` still asserts that per changeset rather than assuming
it, and REPORTS everything it can't migrate rather than silently dropping it.

``QuerySet.update()``, not ``save()`` — ``CitationInstance`` is immutable and
its ``save()`` rejects a row that already has a pk. Retro-filling a
newly-added column on immutable rows is the one sanctioned exception;
superseding instances instead would break their slugs and inline markers.

Reverse blanks exactly the quotes the forward would write (recomputed — the
transform is deterministic), so reverse-then-forward is clean.
"""

from __future__ import annotations

from django.db import migrations

from apps.provenance.note_quote_backfill import quote_candidates


def _forward(apps, schema_editor):
    CitationInstance = apps.get_model("citation", "CitationInstance")
    migrated = 0
    reports: list[str] = []
    for candidate in quote_candidates(apps):
        if candidate.reason is not None:
            reports.append(
                f"changeset {candidate.changeset.pk}: {candidate.reason}: "
                f"{candidate.changeset.note[:80]}"
            )
            continue
        assert candidate.instances is not None and candidate.extracted is not None
        pending = [
            inst.pk
            for inst in candidate.instances
            if inst.quote != candidate.extracted.quote
        ]
        if pending:
            CitationInstance.objects.filter(pk__in=pending).update(
                quote=candidate.extracted.quote
            )
        migrated += 1
    print(f"\n  populated quotes for {migrated} changesets")
    for line in reports:
        print(f"  SKIP {line}")


def _reverse(apps, schema_editor):
    CitationInstance = apps.get_model("citation", "CitationInstance")
    for candidate in quote_candidates(apps):
        if candidate.reason is not None or candidate.instances is None:
            continue
        assert candidate.extracted is not None
        CitationInstance.objects.filter(
            pk__in=[inst.pk for inst in candidate.instances],
            quote=candidate.extracted.quote,
        ).update(quote="")


class Migration(migrations.Migration):
    dependencies = [
        (
            "provenance",
            "0022_remove_claim_provenance_claim_citation_max_length_and_more",
        ),
        ("citation", "0014_citationinstance_quote_and_more"),
    ]

    operations = [
        migrations.RunPython(_forward, _reverse),
    ]
