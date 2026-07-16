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

from django.db.models import CharField, ForeignKey, IntegerField

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
    _str_or_none_from_column,
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
    """Precomputed per-key-member facts the extract closure reads on every claim.

    ``valid_pks`` is the target table's primary keys for an FK member (empty and
    unused for a literal member). ``nullable`` (FK members only) lets a null
    identity part pass through as ``None`` instead of dropping the claim.
    """

    value_key: ClaimValueKey
    is_fk: bool
    valid_pks: frozenset[int]
    nullable: bool = False


class _PayloadPlan(NamedTuple):
    """The resolved data-column shape: through-columns, value-keys and scalar types.

    Everything reconciled *by value* rather than *by key* — non-identity
    members first, then payload — so an in-place row update covers both.
    Positionally aligned: ``columns[i]`` materializes ``value_keys[i]``, whose
    scalar shape is ``kinds[i]`` (``int`` or ``str``).
    """

    columns: list[ColumnName]
    value_keys: tuple[ClaimValueKey, ...]
    kinds: tuple[type, ...]


def build_through_projection(
    binding: ClaimRelationshipBinding,
) -> ThroughRowProjection[Any, Any] | None:
    """Build the projection for one relationship binding, or ``None`` to skip.

    Drives entirely off ``binding.spec`` + ``binding.through_model._meta``: the
    subject column from ``binding.subject_fk``, each member's column and FK-vs-
    literal nature from ``get_field``, the codecs from member/payload arity.
    Reconcile rows are keyed by the spec's **identity members only**; a
    non-identity member materializes as a data column beside the payload, so
    changing its value updates the row in place (same pk, citations intact)
    instead of delete+create. Returns ``None`` when an FK member declares
    :attr:`EmptyTargetPolicy.SKIP_NAMESPACE` and its target table is empty — the
    sole guard (credit ``role``) against an unseeded vocabulary wiping rows.

    Called fresh on each resolve, so the target-PK sets are always current.
    """
    spec = binding.spec
    through_model = binding.through_model

    member_infos: list[_MemberInfo] = []
    key_columns: list[ColumnName] = []
    data_columns: list[ColumnName] = []
    data_value_keys: list[ClaimValueKey] = []
    data_kinds: list[type] = []
    for member in spec.members:
        field = through_model._meta.get_field(member.field)
        value_key = member.value_key or member.field
        if isinstance(field, ForeignKey):
            if member.identity is None:
                # A non-identity FK member would need pk validation on the
                # data path (the extract guard below covers key members only).
                # No spec declares one; fail loud rather than write unchecked
                # pks into a column.
                raise NotImplementedError(
                    f"{through_model.__name__}.{member.field}: non-identity FK "
                    "members are not supported by the through projection."
                )
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
            member_infos.append(
                _MemberInfo(value_key, True, valid_pks, member.nullable)
            )
            key_columns.append(f"{member.field}_id")
        elif member.identity is not None:
            member_infos.append(_MemberInfo(value_key, False, frozenset()))
            key_columns.append(member.field)
        else:
            # Non-identity literal member: reconciled by value, not by key.
            data_columns.append(member.field)
            data_value_keys.append(value_key)
            data_kinds.append(str)

    payload = _resolve_payload(binding)
    data = _PayloadPlan(
        columns=data_columns + payload.columns,
        value_keys=(*data_value_keys, *payload.value_keys),
        kinds=(*data_kinds, *payload.kinds),
    )

    columns_to_key, key_to_columns = _key_codecs(member_infos)
    columns_to_payload, payload_to_columns = _payload_codecs(data)
    extract = _make_extractor(member_infos, data.value_keys)

    return ThroughRowProjection(
        subject_model=binding.subject_model,
        field_name=spec.namespace,
        through_model=through_model,
        subject_column=f"{binding.subject_fk}_id",
        key_columns=tuple(key_columns),
        payload_columns=tuple(data.columns),
        extract_member=extract,
        columns_to_key=columns_to_key,
        key_to_columns=key_to_columns,
        columns_to_payload=columns_to_payload,
        payload_to_columns=payload_to_columns,
        ignore_conflicts=spec.ignore_conflicts,
    )


def _resolve_payload(binding: ClaimRelationshipBinding) -> _PayloadPlan:
    """The payload columns, value-keys and scalar kinds, type-checked per field.

    Each payload field must be an ``IntegerField`` or ``CharField`` — the two
    extant payload scalar shapes (gameplay ``count``; model-relationship
    ``relationship_type``/``license_status``). The guard is a *type* check, not
    an arity check, so a future decimal/bool ``PayloadField`` fails loudly here
    rather than silently taking a scalar converter. Nullability is not part of
    the predicate: a non-nullable value reads correctly under the ``…_or_none``
    decoders (merely a wider read type).
    """
    columns: list[ColumnName] = []
    value_keys: list[ClaimValueKey] = []
    kinds: list[type] = []
    for pf in binding.spec.payload:
        field = binding.through_model._meta.get_field(pf.field)
        if isinstance(field, IntegerField):
            kinds.append(int)
        elif isinstance(field, CharField):
            kinds.append(str)
        else:
            raise NotImplementedError(
                f"{binding.through_model.__name__}: payload field {pf.field!r} "
                f"is {type(field).__name__}, but only integer and string "
                "payloads are supported."
            )
        columns.append(pf.field)
        value_keys.append(pf.value_key or pf.field)
    return _PayloadPlan(columns, tuple(value_keys), tuple(kinds))


def _key_codecs(member_infos: list[_MemberInfo]) -> ColumnCodec:
    """Column⇄member-key codecs, by key-member cardinality and FK-vs-literal.

    A single *nullable* FK key member declares the ``int | None`` decoder: the
    non-nullable ``_int_from_column`` is a ``cast`` (a runtime no-op), so
    mis-picking it would silently type a NULL key as ``int`` rather than crash
    — the honest decoder keeps the declared type true.
    """
    if len(member_infos) == 1:
        only = member_infos[0]
        if only.is_fk:
            if only.nullable:
                return _int_or_none_from_column, _one_column
            return _int_from_column, _one_column
        return _str_from_column, _one_column
    return _compound_key, _compound_columns


def _payload_codecs(payload: _PayloadPlan) -> ColumnCodec:
    """Column⇄payload codecs, by payload arity and scalar kind.

    A multi-column payload rides the compound (tuple-identity) codecs, same as
    a compound member key.
    """
    if not payload.columns:
        return _no_payload, _no_columns
    if len(payload.columns) == 1:
        from_column = (
            _int_or_none_from_column
            if payload.kinds[0] is int
            else _str_or_none_from_column
        )
        return from_column, _one_column
    return _compound_key, _compound_columns


def _make_extractor(
    member_infos: list[_MemberInfo],
    payload_value_keys: tuple[ClaimValueKey, ...],
) -> MemberExtractor[Any, Any]:
    """Build the per-claim ``extract`` — the one per-shape step of reconcile.

    ``member_infos`` covers the *key* members only; ``payload_value_keys``
    covers everything reconciled by value (non-identity members + payload),
    read with ``val.get`` — write-time validation requires non-identity
    members on positive claims, and tombstones are filtered before extract.

    The unified key guard collapses the hand-written builders' three variants
    into the strictest: tolerate a null ``claim.value`` (location's guard),
    require an ``int`` value present in the target-PK set for every FK member
    (the M2M guard, which also drops a ``True``-as-pk), and drop a literal
    member only when its value is missing. A *nullable* FK member passes
    ``None`` through as an absent identity part instead — only a non-null
    unresolved value drops the claim.
    """
    single_member = len(member_infos) == 1
    single_payload = payload_value_keys[0] if len(payload_value_keys) == 1 else None

    def extract(claim: Claim) -> ExtractedMember[Any, Any] | None:
        val = cast(Mapping[str, object], claim.value or {})
        keys: list[object] = []
        for mi in member_infos:
            raw = val.get(mi.value_key)
            if mi.is_fk:
                if raw is None and mi.nullable:
                    keys.append(None)
                    continue
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
        payload: object
        if not payload_value_keys:
            payload = None
        elif single_payload is not None:
            payload = val.get(single_payload)
        else:
            payload = tuple(val.get(k) for k in payload_value_keys)
        return ExtractedMember(key, payload)

    return extract
