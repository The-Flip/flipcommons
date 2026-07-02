"""Shared machinery for the note-quote backfill migrations.

One definition of "migratable" for both halves of the backfill —
``provenance/0023`` (populate quotes) and ``provenance/0024`` (strip notes) —
so the strip can never touch a note the populate didn't verifiably land.
The pure text transform lives in :mod:`apps.provenance.note_quotes`; this
module adds the DB walk around it.

Imported by migrations ``provenance/0023`` and ``provenance/0024``: do NOT
delete this module or change its semantics — migration replays on fresh
databases depend on it behaving exactly as it did when they shipped.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, NamedTuple

from apps.provenance.note_quotes import ExtractedQuote, extract_quote

# The provenance/0011 backfill boilerplate; never quote-shaped, skipped fast.
SEED_NOTE = "Seed import (backfilled)."

# The note's source phrase implies acceptable source-name substrings for the
# sources we can check (abbreviation and full name both count). A miss means
# the note quotes one source while the changeset cites another — writing the
# quote would mis-attribute it, so the row is skipped and reported for hand
# review.
SOURCE_NAME_HINTS: dict[str, tuple[str, ...]] = {
    "ipdb": ("ipdb", "internet pinball database"),
    "opdb": ("opdb", "open pinball database"),
    "wikipedia": ("wikipedia",),
    "kineticist": ("kineticist",),
    "eremeka": ("eremeka",),
    "early arcades japan": ("early arcades japan",),
}


class QuoteCandidate(NamedTuple):
    """One non-empty note's disposition in the backfill.

    ``instances`` is the list of historical ``CitationInstance`` rows the
    quote belongs on, and is only set when ``reason`` is ``None``; a skipped
    row instead carries the human-readable ``reason`` for the report.
    """

    changeset: Any  # historical ChangeSet model instance
    extracted: ExtractedQuote | None
    instances: list[Any] | None  # historical CitationInstance rows
    reason: str | None


def _source_names(instance: Any) -> str:  # noqa: ANN401 - historical model
    """The instance's source name plus its parent's, lowered, for hint checks."""
    source = instance.citation_source
    names = str(source.name)
    if source.parent_id is not None:
        names += " " + source.parent.name
    return names.lower()


def _instances_match_source(instances: list[Any], source_phrase: str) -> bool:
    """False only when the note names a checkable source the cite disagrees with."""
    phrase = source_phrase.lower()
    for token, name_tokens in SOURCE_NAME_HINTS.items():
        if token in phrase:
            return all(
                any(name_token in _source_names(inst) for name_token in name_tokens)
                for inst in instances
            )
    return True


# ``apps`` is a migration StateApps registry — typed ``Any`` because the
# historical models it yields have no importable static type.
def quote_candidates(apps: Any) -> Iterator[QuoteCandidate]:  # noqa: ANN401
    """Yield every non-seed note's backfill disposition, in changeset order.

    Shared by 0023's forward (write quotes) and reverse (blank them) and
    0024's strip guard. A recognized note is migratable only when its
    changeset has field-level instances (via the ``ClaimCitationInstance``
    join — inline instances have no join rows), they all cite one source,
    that source agrees with the note's named source and no instance already
    carries a different quote.
    """
    ChangeSet = apps.get_model("provenance", "ChangeSet")
    CitationInstance = apps.get_model("citation", "CitationInstance")

    notes = (
        ChangeSet.objects.exclude(note="")
        .exclude(note=SEED_NOTE)
        .only("id", "note")
        .order_by("id")
    )
    for changeset in notes.iterator():
        extracted = extract_quote(changeset.note)
        if extracted is None:
            if '"' in changeset.note:
                yield QuoteCandidate(
                    changeset, None, None, "unrecognized quote-shaped note"
                )
            continue
        instances = list(
            CitationInstance.objects.filter(claims__changeset=changeset)
            .distinct()
            .select_related("citation_source", "citation_source__parent")
        )
        if not instances:
            yield QuoteCandidate(changeset, extracted, None, "no citation instances")
            continue
        if len({inst.citation_source_id for inst in instances}) > 1:
            yield QuoteCandidate(
                changeset, extracted, None, "instances span several sources"
            )
            continue
        if not _instances_match_source(instances, extracted.source):
            yield QuoteCandidate(
                changeset,
                extracted,
                None,
                f"note quotes {extracted.source!r} but instances cite "
                f"{instances[0].citation_source.name!r}",
            )
            continue
        if any(inst.quote and inst.quote != extracted.quote for inst in instances):
            yield QuoteCandidate(
                changeset, extracted, None, "instance already carries a quote"
            )
            continue
        yield QuoteCandidate(changeset, extracted, instances, None)
