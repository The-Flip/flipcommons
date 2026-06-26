"""Catalog-free resolution primitives.

The shared kernel between *rank*
(:func:`apps.provenance.claim_ranking_in_db.ranked_claims`) and the per-shape
desired/diff/write logic — the layer-2 winner-pick (:func:`pick_winners`) and the
layer-3 reconcile (:func:`reconcile`).

Deliberately catalog-free — it imports only provenance (+ Django ORM base
classes) and names no concrete catalog model — so it can move wholesale to
``apps.provenance.resolution``. An import-linter contract pins that boundary;
concrete :class:`Projection` instances (which name catalog/media models) live in
``_relationships.py`` / ``_media.py``, never here.
"""

from __future__ import annotations

from collections.abc import Hashable
from typing import TYPE_CHECKING, NamedTuple, Protocol

from apps.provenance.claim_presence import member_is_present

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from apps.provenance.models import Claim

type Winners[Subject: Hashable, Group: Hashable] = dict[Subject, dict[Group, "Claim"]]
"""Winning claim per ``(subject, group)`` — the first claim seen for each group
key within each subject, which is the highest-ranked one.  Both keys are
``Hashable`` because they index nested dicts."""


def pick_winners[Subject: Hashable, Group: Hashable](
    ranked: Iterable[Claim],
    subject: Callable[[Claim], Subject],
    group: Callable[[Claim], Group],
) -> Winners[Subject, Group]:
    """First (highest-ranked) claim per ``(subject, group)``.

    Folds a :func:`ranked_claims` queryset — already ordered so the first row
    per group is the winner — into a two-level map.  ``setdefault`` keeps the
    first claim seen for each group key, so a later (lower-ranked) claim for the
    same key is dropped.

    *subject* and *group* extract the keys from each claim — group on
    ``claim_key`` for membership sets (see :func:`pick_member_winners`) or on
    ``field_name`` for scalar registers, subject usually ``object_id`` but
    occasionally a composite key.
    """
    winners: Winners[Subject, Group] = {}
    for claim in ranked:
        winners.setdefault(subject(claim), {}).setdefault(group(claim), claim)
    return winners


def pick_member_winners(ranked: Iterable[Claim]) -> Winners[int, str]:
    """Membership winner-pick: one winner per ``claim_key`` per entity.

    Subject is the entity ``object_id``, group is the ``claim_key`` — a thin
    partial application of :func:`pick_winners` for the common case.
    """
    return pick_winners(ranked, lambda c: c.object_id, lambda c: c.claim_key)


# ---------------------------------------------------------------------------
# Layer-3: reconcile — the desired-state controller loop
# ---------------------------------------------------------------------------
#
# A membership projection materializes a claim namespace into through-rows.
# ``reconcile`` is the single loop the 9 (formerly copy-pasted) resolvers share:
# pick winners → build desired → read existing → diff → write the delta.
#
# Three type params, spelled out and bound to match ``pick_winners``:
#   * ``Subject`` — the entity key (``object_id``, or a composite ``EntityKey``)
#   * ``Member``  — the member identity (target pk, ``(person, role)`` tuple, …)
#   * ``Payload`` — the member's attribute (``None`` for a set; a value for a map)


type RowId = int
"""A materialized through-row's primary key — what a delete/update targets.
Distinct from ``Subject`` (often the entity ``object_id``): a documentation
alias so the ``pk`` fields and the delete list read as row identities, not bare
ints."""


type MemberMap[Subject: Hashable, Member: Hashable, Payload] = dict[
    Subject, dict[Member, Payload]
]
"""Desired *and* existing-payload share this shape — keyed by subject, then by
member.  A set membership is ``Payload = None``; a map membership carries a value."""


class RowState[Payload](NamedTuple):
    """An existing materialized row: its pk (for delete/update) and payload."""

    pk: RowId
    payload: Payload


class ExtractedMember[Member: Hashable, Payload](NamedTuple):
    """What :meth:`Projection.extract` returns for one winning claim."""

    key: Member
    payload: Payload


class CreateRow[Subject: Hashable, Member: Hashable, Payload](NamedTuple):
    """A row to insert — no pk yet."""

    subject: Subject
    key: Member
    payload: Payload


class UpdateRow[Payload](NamedTuple):
    """An existing row whose payload changed (a map-membership value edit)."""

    pk: RowId
    payload: Payload


class Delta[Subject: Hashable, Member: Hashable, Payload](NamedTuple):
    """What :func:`reconcile` writes — the create/delete/update partition."""

    create: list[CreateRow[Subject, Member, Payload]]
    delete: list[RowId]
    update: list[UpdateRow[Payload]]


class Projection[Subject: Hashable, Member: Hashable, Payload](Protocol):
    """Per-shape strategy: claim source, key extraction, row read and write.

    Everything that varies between the membership resolvers lives behind these
    five methods; :func:`reconcile` is the invariant loop over them.
    """

    def claims(self, subjects: set[Subject] | None) -> Iterable[Claim]:
        """Ranked active claims for this namespace, scoped to *subjects* (or all)."""
        ...

    def subject(self, claim: Claim) -> Subject:
        """The subject key for a claim — ``object_id`` or a composite."""
        ...

    def extract(self, claim: Claim) -> ExtractedMember[Member, Payload] | None:
        """The desired ``(key, payload)`` for a winning claim, or ``None`` to drop
        it (invalid target pk, bad category — the per-shape validation hook)."""
        ...

    def read(
        self, subjects: set[Subject] | None
    ) -> MemberMap[Subject, Member, RowState[Payload]]:
        """Existing materialized rows, scoped to *subjects* (or all)."""
        ...

    def write(self, delta: Delta[Subject, Member, Payload]) -> None:
        """Apply the delta — delete, bulk-create, bulk-update through-rows."""
        ...


def reconcile[Subject: Hashable, Member: Hashable, Payload](
    projection: Projection[Subject, Member, Payload], subjects: set[Subject] | None
) -> Delta[Subject, Member, Payload]:
    """Converge a projection's materialized rows to its claims for *subjects*.

    Level-triggered: recomputes desired from the current claims regardless of
    what changed, so re-running is idempotent (the second pass writes nothing).
    *subjects* scopes the work — a single pk for an interactive edit, the whole
    affected set for bulk, ``None`` for the entire namespace.  Returns the
    :class:`Delta` so a caller can scope cache invalidation (POST1).
    """
    winners = pick_winners(
        projection.claims(subjects), projection.subject, lambda c: c.claim_key
    )
    desired = _build_desired(projection, winners)
    existing = projection.read(subjects)
    delta = diff(desired, existing)
    projection.write(delta)
    return delta


def _build_desired[Subject: Hashable, Member: Hashable, Payload](
    projection: Projection[Subject, Member, Payload],
    winners: Winners[Subject, str],
) -> MemberMap[Subject, Member, Payload]:
    """Fold winning claims into the desired member map, dropping tombstones.

    ``member_is_present`` (the ``exists=false`` retraction filter) is the one
    universal built-in run here for every projection; all other per-shape
    validation lives in :meth:`Projection.extract`, which returns ``None`` to
    drop a member.
    """
    desired: MemberMap[Subject, Member, Payload] = {}
    for subject, group_winners in winners.items():
        members: dict[Member, Payload] = {}
        for claim in group_winners.values():
            if not member_is_present(claim):
                continue
            member = projection.extract(claim)
            if member is not None:
                members[member.key] = member.payload
        desired[subject] = members
    return desired


def diff[Subject: Hashable, Member: Hashable, Payload](
    desired: MemberMap[Subject, Member, Payload],
    existing: MemberMap[Subject, Member, RowState[Payload]],
) -> Delta[Subject, Member, Payload]:
    """Three-way set/map difference: create, delete, update.

    The diff domain is ``desired ∪ existing`` subjects — a subject whose claims
    all went away is still visited so its stale rows are deleted.  The update
    branch is vacuous when ``Payload`` is ``None`` (a set has no value to
    differ on), so plain through-rows get ``{create, delete}`` for free.
    """
    create: list[CreateRow[Subject, Member, Payload]] = []
    delete: list[RowId] = []
    update: list[UpdateRow[Payload]] = []
    for subject in desired.keys() | existing.keys():
        want = desired.get(subject, {})
        have = existing.get(subject, {})
        for key, payload in want.items():
            if key not in have:
                create.append(CreateRow(subject, key, payload))
            elif have[key].payload != payload:
                update.append(UpdateRow(have[key].pk, payload))
        for key, row in have.items():
            if key not in want:
                delete.append(row.pk)
    return Delta(create, delete, update)
