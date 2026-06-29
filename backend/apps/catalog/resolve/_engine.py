"""Catalog-free resolution primitives.

The shared kernel between *rank*
(:func:`apps.provenance.claim_ranking_in_db.ranked_claims`) and the per-shape
desired/diff/write logic: the layer-2 winner-pick (:func:`pick_winners`), the
layer-3 reconcile (:func:`reconcile`), the typed vocabulary they speak
(:class:`Projection`, :class:`Delta`, …) and the generic, shape-agnostic
:class:`ThroughRowProjection` that implements :class:`Projection` for every
plain/payload/compound through-row namespace.

Deliberately catalog-free — it imports only provenance (+ the Django ORM) and
names no concrete catalog model (through models arrive as constructor
arguments) — so it can move wholesale to ``apps.provenance.resolution``. An
import-linter contract pins that boundary. The *bespoke* projections
(:class:`~._relationships.AliasProjection`, :class:`~._media.MediaProjection`)
and the concrete builders that configure :class:`ThroughRowProjection` name
domain models and live in ``_relationships.py`` / ``_media.py``, never here.
"""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple, Protocol, cast

from django.contrib.contenttypes.models import ContentType

from apps.core.types import ClaimFieldName, ClaimKey, ClaimSubjectId, ColumnName
from apps.provenance.claim_presence import member_is_present
from apps.provenance.claim_ranking_in_db import ranked_claims
from apps.provenance.models import Claim

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from django.db.models import Model

    from apps.provenance.models import ClaimControlledModel

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


def pick_member_winners(ranked: Iterable[Claim]) -> Winners[ClaimSubjectId, ClaimKey]:
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
# ``reconcile`` is the single loop every membership resolver shares:
# pick winners → build desired → read existing → diff → write the delta.
#
# Three type params, spelled out and bound to match ``pick_winners``:
#   * ``Subject`` — the entity key (``object_id``, or a composite ``EntityKey``)
#   * ``Member``  — the member identity (target pk, ``(person, role)`` tuple, …)
#   * ``Payload`` — the member's attribute (``None`` for a set; a value for a map)


type MaterializedRowId = int
"""The primary key of a row in the materialized catalog view — the identity a
reconcile deletes or updates by. Distinct from the entity ``ClaimSubjectId`` and
a member's target pk it sits beside."""


type MemberMap[Subject: Hashable, Member: Hashable, Payload] = dict[
    Subject, dict[Member, Payload]
]
"""Desired *and* existing-payload share this shape — keyed by subject, then by
member.  A set membership is ``Payload = None``; a map membership carries a value."""


class RowState[Payload](NamedTuple):
    """An existing materialized row: its pk (for delete/update) and payload."""

    pk: MaterializedRowId
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

    pk: MaterializedRowId
    payload: Payload


class Delta[Subject: Hashable, Member: Hashable, Payload](NamedTuple):
    """What :func:`reconcile` writes — the create/delete/update partition."""

    create: list[CreateRow[Subject, Member, Payload]]
    delete: list[MaterializedRowId]
    update: list[UpdateRow[Payload]]


class Projection[Subject: Hashable, Member: Hashable, Payload](Protocol):
    """Per-shape strategy: claim source, key extraction, row read and write.

    Everything that varies between the membership resolvers lives behind these
    five methods; :func:`reconcile` is the invariant loop over them.

    **Purity invariant.** A projection is a function of *claims* — it reads the
    claim log (plus its own materialized rows, for the diff) and writes its own
    view, nothing else. It must **never** read another projection's materialized
    output: that is what creates cross-entity ordering, cascade edges and
    staleness (the ``model_abbreviations`` reading ``TitleAbbreviation`` rows
    that motivated this design). A cross-projection or cross-entity join belongs
    at *read* time, not here. The one tolerated exception is the FK natural-key
    lookup (a target's resolved ``slug`` / ``location_path``), safe only because
    the resolved pk is stable and the dependency is met by batch *order*, not an
    incremental trigger.
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
    :class:`Delta` so a caller can scope cache invalidation.
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
    winners: Winners[Subject, ClaimKey],
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
    delete: list[MaterializedRowId] = []
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


# ---------------------------------------------------------------------------
# The generic through-row Projection
# ---------------------------------------------------------------------------
#
# One data-parameterized Projection covers every plain/payload/compound
# through-row shape (themes, reward types, tags, gameplay features, credits,
# abbreviations, parent hierarchies, corporate-entity locations): the through
# model, its subject/member/payload columns and the write flags are all
# constructor arguments, so it names no concrete model. The two genuinely
# bespoke projections — AliasProjection (case-folded keys) and MediaProjection
# (composite EntityKey subject) — stay in their domain modules.


type ColumnValues = tuple[object, ...]
"""The values of one materialized row's key or payload columns, in positional
order."""

type ColumnNames = tuple[ColumnName, ...]
"""The through-table column names that back a member key or a payload, in
positional order."""

type MemberExtractor[Member: Hashable, Payload] = Callable[
    [Claim], ExtractedMember[Member, Payload] | None
]
"""Derives a through-row's desired key and payload from a winning claim, or
``None`` to drop it. The single per-shape step in an otherwise uniform reconcile."""


# Column <-> Member/Payload converters.  The ``*_to_columns`` direction takes
# ``object`` (a Member or Payload) — contravariantly assignable to any concrete
# param type — while the ``columns_to_*`` direction must return the precise type,
# so the scalar cases are spelled per result type (int / str / int|None).


def _int_from_column(columns: ColumnValues) -> int:
    """Single int column → its value (FK target pk)."""
    return cast(int, columns[0])


def _str_from_column(columns: ColumnValues) -> str:
    """Single str column → its value (abbreviation string)."""
    return cast(str, columns[0])


def _int_or_none_from_column(columns: ColumnValues) -> int | None:
    """Single nullable int column → its value (gameplay count)."""
    return cast(int | None, columns[0])


def _one_column(value: object) -> ColumnValues:
    """A scalar Member/Payload → its single column."""
    return (value,)


def _no_payload(columns: ColumnValues) -> None:
    """Set membership: no payload columns → ``None`` payload."""
    return None


def _no_columns(payload: object) -> ColumnValues:
    """Set membership: ``None`` payload → no payload columns."""
    return ()


def _compound_key(columns: ColumnValues) -> tuple[object, ...]:
    """Multi-column member key → the column tuple itself (identity).

    A compound ``Member`` (e.g. credit's ``(person_id, role_id)``) is the column
    tuple unchanged; the values already arrive as a tuple from ``values_list``.
    A plain tuple keys ``reconcile``'s maps identically to a NamedTuple, so the
    member type stays internal and never reaches the materialized row.
    """
    return columns


def _compound_columns(key: object) -> ColumnValues:
    """A compound (tuple) member key → its columns (identity)."""
    return cast(ColumnValues, key)


@dataclass(frozen=True, slots=True)
class ThroughRowProjection[Member: Hashable, Payload]:
    """Generic membership projection over a through-table.

    The through model, its subject/member/payload columns and the create-time
    write flags are all data, so one class instantiates for themes, reward
    types, tags, gameplay features, credits, abbreviations, parent hierarchies
    and corporate-entity locations.  ``Member`` is a single pk/value or a
    compound :class:`~typing.NamedTuple` key; ``Payload`` is ``None`` for a set
    or a single attribute (e.g. gameplay ``count``) for a map.
    """

    subject_model: type[ClaimControlledModel]
    field_name: ClaimFieldName
    through_model: type[Model]
    subject_column: str
    key_columns: ColumnNames
    payload_columns: ColumnNames
    extract_member: MemberExtractor[Member, Payload]
    columns_to_key: Callable[[ColumnValues], Member]
    key_to_columns: Callable[[Member], ColumnValues]
    columns_to_payload: Callable[[ColumnValues], Payload]
    payload_to_columns: Callable[[Payload], ColumnValues]
    ignore_conflicts: bool = False

    def claims(self, subjects: set[ClaimSubjectId] | None) -> Iterable[Claim]:
        ct = ContentType.objects.get_for_model(self.subject_model)
        claims_qs = Claim.objects.filter(content_type=ct, field_name=self.field_name)
        if subjects is not None:
            claims_qs = claims_qs.filter(object_id__in=subjects)
        return ranked_claims(claims_qs, "object_id", "claim_key")

    def subject(self, claim: Claim) -> ClaimSubjectId:
        return claim.object_id

    def extract(self, claim: Claim) -> ExtractedMember[Member, Payload] | None:
        return self.extract_member(claim)

    def read(
        self, subjects: set[ClaimSubjectId] | None
    ) -> MemberMap[ClaimSubjectId, Member, RowState[Payload]]:
        manager = self.through_model._default_manager
        if subjects is not None:
            rows_qs = manager.filter(**{f"{self.subject_column}__in": subjects})
        else:
            # A NULL subject column means the row belongs to a sibling namespace
            # sharing this table — Credit's model/series XOR is the only case.
            # A full-scope read must exclude those, or diff() would bucket them
            # under a null subject and delete them. A no-op for non-null columns.
            rows_qs = manager.filter(**{f"{self.subject_column}__isnull": False})

        nkeys = len(self.key_columns)
        columns = ("pk", self.subject_column, *self.key_columns, *self.payload_columns)
        existing: MemberMap[ClaimSubjectId, Member, RowState[Payload]] = {}
        for row in rows_qs.values_list(*columns):
            pk, subject_id = row[0], row[1]
            key = self.columns_to_key(row[2 : 2 + nkeys])
            payload = self.columns_to_payload(row[2 + nkeys :])
            existing.setdefault(subject_id, {})[key] = RowState(pk, payload)
        return existing

    def write(self, delta: Delta[ClaimSubjectId, Member, Payload]) -> None:
        manager = self.through_model._default_manager
        if delta.delete:
            manager.filter(pk__in=delta.delete).delete()
        if delta.create:
            rows = [
                self.through_model(
                    **{self.subject_column: row.subject},
                    **dict(
                        zip(
                            self.key_columns,
                            self.key_to_columns(row.key),
                            strict=True,
                        )
                    ),
                    **dict(
                        zip(
                            self.payload_columns,
                            self.payload_to_columns(row.payload),
                            strict=True,
                        )
                    ),
                )
                for row in delta.create
            ]
            manager.bulk_create(
                rows, batch_size=2000, ignore_conflicts=self.ignore_conflicts
            )
        if delta.update:
            fetched = manager.in_bulk([row.pk for row in delta.update])
            for row in delta.update:
                instance = fetched[row.pk]
                for column, value in zip(
                    self.payload_columns,
                    self.payload_to_columns(row.payload),
                    strict=True,
                ):
                    setattr(instance, column, value)
            manager.bulk_update(
                list(fetched.values()), list(self.payload_columns), batch_size=2000
            )
