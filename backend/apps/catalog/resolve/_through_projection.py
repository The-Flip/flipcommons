"""The generic spec→projection bridge: ``build_through_projection``.

One data-driven function reads a through-model's :class:`ClaimRelationshipSpec`
(declared as a ClassVar, paired with its subject in a
:class:`ClaimRelationshipBinding`) plus Django ``_meta`` and instantiates the
configured :class:`~._engine.ThroughRowProjection` — replacing the hand-written
``_*_projection`` builders for every explicit-ClassVar relationship shape
(themes, tags, reward types, gameplay features, credits, abbreviations,
corporate-entity locations, and the self-referential parent hierarchies).

Catalog-free by construction: it names no concrete catalog model (every domain
fact comes from the binding + ``_meta``) and imports only the engine kernel and
the provenance vocabulary, so it belongs to the would-be-movable resolution
core. Only the bespoke ``AliasProjection`` (case-folded keys) stays hand-written
in :mod:`._relationships`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NamedTuple, cast

from django.db.models import ForeignKey, IntegerField

from apps.provenance.model_bases import (
    ClaimRelationshipBinding,
    EmptyTargetPolicy,
)

from ._engine import (
    ColumnValues,
    ExtractedMember,
    MemberExtractor,
    ThroughRowProjection,
    _compound_columns,
    _compound_key,
    _int_from_column,
    _int_or_none_from_column,
    _no_columns,
    _no_payload,
    _one_column,
    _str_from_column,
)

if TYPE_CHECKING:
    from apps.core.types import ClaimValueKey, ColumnName
    from apps.provenance.models import Claim

logger = logging.getLogger(__name__)


type ColumnDecoder = Callable[[ColumnValues], Any]
"""Reads a member key or payload value *from* its materialized columns — the
engine's ``columns_to_key`` / ``columns_to_payload``. The value is ``Any``
because its type varies by shape (the builder erases the engine's type params)."""

type ColumnEncoder = Callable[[Any], ColumnValues]
"""Writes a member key or payload value *back to* its columns — the engine's
``key_to_columns`` / ``payload_to_columns`` (``Any`` value, as above)."""

type ColumnCodec = tuple[ColumnDecoder, ColumnEncoder]
"""A through-row converter pair, ``(decode, encode)``."""


@dataclass(frozen=True, slots=True)
class _MemberInfo:
    """Precomputed per-member facts the extract closure reads on every claim.

    ``valid_pks`` is the target table's primary keys for an FK member (empty and
    unused for a literal member).
    """

    value_key: ClaimValueKey
    is_fk: bool
    valid_pks: frozenset[int]


class _PayloadPlan(NamedTuple):
    """The resolved payload shape: its through-columns and the claim value-key."""

    columns: list[ColumnName]
    value_key: ClaimValueKey | None


def build_through_projection(
    binding: ClaimRelationshipBinding,
) -> ThroughRowProjection[Any, Any] | None:
    """Build the projection for one relationship binding, or ``None`` to skip.

    Drives entirely off ``binding.spec`` + ``binding.through_model._meta``: the
    subject column from ``binding.subject_fk``, each member's column and FK-vs-
    literal nature from ``get_field``, the codecs from member/payload arity.
    Returns ``None`` when an FK member declares
    :attr:`EmptyTargetPolicy.SKIP_NAMESPACE` and its target table is empty — the
    sole guard (credit ``role``) against an unseeded vocabulary wiping rows.

    Called fresh on each resolve, so the target-PK sets are always current.
    """
    spec = binding.spec
    through_model = binding.through_model

    member_infos: list[_MemberInfo] = []
    key_columns: list[ColumnName] = []
    for member in spec.members:
        field = through_model._meta.get_field(member.field)
        value_key = member.value_key or member.field
        if isinstance(field, ForeignKey):
            target = field.related_model
            # related_model is a class once apps are loaded (never "self" here).
            assert not isinstance(target, str)
            valid_pks = frozenset(target._default_manager.values_list("pk", flat=True))
            if (
                not valid_pks
                and member.empty_target is EmptyTargetPolicy.SKIP_NAMESPACE
            ):
                logger.warning(
                    "%s table is empty — skipping %r resolution until it is seeded.",
                    target.__name__,
                    spec.namespace,
                )
                return None
            member_infos.append(_MemberInfo(value_key, True, valid_pks))
            key_columns.append(f"{member.field}_id")
        else:
            member_infos.append(_MemberInfo(value_key, False, frozenset()))
            key_columns.append(member.field)

    payload = _resolve_payload(binding)

    columns_to_key, key_to_columns = _key_codecs(member_infos)
    columns_to_payload, payload_to_columns = _payload_codecs(bool(payload.columns))
    extract = _make_extractor(member_infos, payload.value_key)

    return ThroughRowProjection(
        subject_model=binding.subject_model,
        field_name=spec.namespace,
        through_model=through_model,
        subject_column=f"{binding.subject_fk}_id",
        key_columns=tuple(key_columns),
        payload_columns=tuple(payload.columns),
        extract_member=extract,
        columns_to_key=columns_to_key,
        key_to_columns=key_to_columns,
        columns_to_payload=columns_to_payload,
        payload_to_columns=payload_to_columns,
        ignore_conflicts=spec.ignore_conflicts,
    )


def _resolve_payload(binding: ClaimRelationshipBinding) -> _PayloadPlan:
    """The payload column + value-key, after the loud single-int-payload guard.

    Codec selection is narrowed to the one extant payload shape — a single
    integer field (gameplay ``count``). The guard is a *type* check, not an arity
    check, so a future single string/decimal ``PayloadField`` fails loudly here
    rather than silently taking the int converter. Nullability is not part of the
    predicate: a non-nullable int reads correctly under ``_int_or_none_from_column``
    (merely a wider read type). Full type-driven selection lands with a second
    payload shape.
    """
    payload = binding.spec.payload
    if not payload:
        return _PayloadPlan([], None)
    if len(payload) > 1:
        raise NotImplementedError(
            f"{binding.through_model.__name__}: only a single payload field is "
            f"supported, got {len(payload)}."
        )
    pf = payload[0]
    field = binding.through_model._meta.get_field(pf.field)
    if not isinstance(field, IntegerField):
        raise NotImplementedError(
            f"{binding.through_model.__name__}: payload field {pf.field!r} "
            f"is {type(field).__name__}, but only integer payloads are supported."
        )
    return _PayloadPlan([pf.field], pf.value_key or pf.field)


def _key_codecs(member_infos: list[_MemberInfo]) -> ColumnCodec:
    """Column⇄member-key codecs, by member cardinality and FK-vs-literal."""
    if len(member_infos) == 1:
        from_column = _int_from_column if member_infos[0].is_fk else _str_from_column
        return from_column, _one_column
    return _compound_key, _compound_columns


def _payload_codecs(has_payload: bool) -> ColumnCodec:
    """Column⇄payload codecs — the nullable-int map, or the no-payload set."""
    if has_payload:
        return _int_or_none_from_column, _one_column
    return _no_payload, _no_columns


def _make_extractor(
    member_infos: list[_MemberInfo],
    payload_value_key: ClaimValueKey | None,
) -> MemberExtractor[Any, Any]:
    """Build the per-claim ``extract`` — the one per-shape step of reconcile.

    The unified guard collapses the hand-written builders' three variants into
    the strictest: tolerate a null ``claim.value`` (location's guard), require an
    ``int`` value present in the target-PK set for every FK member (the M2M
    guard, which also drops a ``True``-as-pk), and drop a literal member only
    when its value is missing. Safe today because tombstones are filtered before
    ``extract`` and write-time validation enforces scalar types.
    """
    single_member = len(member_infos) == 1

    def extract(claim: Claim) -> ExtractedMember[Any, Any] | None:
        val = cast(Mapping[str, object], claim.value or {})
        keys: list[object] = []
        for mi in member_infos:
            raw = val.get(mi.value_key)
            if mi.is_fk:
                if type(raw) is not int or raw not in mi.valid_pks:
                    logger.warning(
                        "Unresolved %s %r in claim (subject pk=%s)",
                        mi.value_key,
                        raw,
                        claim.object_id,
                    )
                    return None
            elif raw is None:
                return None
            keys.append(raw)
        key = keys[0] if single_member else tuple(keys)
        payload = val.get(payload_value_key) if payload_value_key is not None else None
        return ExtractedMember(key, payload)

    return extract
