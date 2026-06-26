"""Claim-boundary validation: shared rules for all claim write paths.

Provides ``classify_claim`` for structural claim classification,
``validate_claim_value`` for per-field scalar validation (used by both the
interactive PATCH path and bulk ingest), ``validate_claims_batch`` for
batch-mode validation in the data-patch ingest path, and
``validate_fk_claims_batch`` for batched FK target existence checks,
and ``validate_relationship_claims_batch`` for batched relationship
target checks.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NamedTuple

from django.core.exceptions import (
    FieldDoesNotExist,
    ImproperlyConfigured,
    ValidationError,
)
from django.db import models

from apps.core.validators import SLUG_FORMAT_MESSAGE, SLUG_RE
from apps.provenance.claim_presence import member_is_present
from apps.provenance.models import ClaimControlledModel, get_claim_fields

if TYPE_CHECKING:
    from apps.provenance.models import Claim

logger = logging.getLogger(__name__)

# Claim classification constants.
DIRECT = "direct"
RELATIONSHIP = "relationship"
EXTRA = "extra"
UNRECOGNIZED = "unrecognized"


# ---------------------------------------------------------------------------
# Relationship schema registry
# ---------------------------------------------------------------------------
# Single source of truth for relationship namespaces. Drives claim
# construction, namespace enumeration, write-path shape validation, and
# batch FK existence checks.


@dataclass(frozen=True, slots=True)
class ValueKeySpec:
    """One key in a relationship claim's value dict.

    ``name`` is the key as it appears in the value dict. ``identity``, when
    set, is the label used in the canonical ``claim_key`` identity parts —
    typically equal to ``name`` (e.g. ``"person"``) but occasionally different
    (e.g. ``identity="alias"`` for ``name="alias_value"``). ``None`` means
    this key is non-identity (e.g. ``count``, ``category``, ``alias_display``).

    **INVARIANT**: ``identity is not None`` ⇒ ``required=True``. Enforced at
    registration time in ``register_relationship_schema``.

    ``display_key`` (identity specs only) names a sibling spec whose value is
    this identity's user-facing rendering — e.g. ``alias_value`` declares
    ``display_key="alias_display"`` so resolvers and display engines both
    read the override from one declaration. See
    ``register_relationship_schema`` for the full set of invariants.

    ``max_length`` (optional, string-identity specs only) carries the target
    ``CharField`` length bound, derived from the model at registration. It is
    consumed by the data-patch adapter, which must reject an over-long member
    at plan-build time: SQLite (the patch author's local DB) silently ignores
    ``CharField(max_length=...)``, so an over-long string would pass every
    local check and only fail as an ``IntegrityError`` on Postgres in prod.
    ``None`` for FK and non-length-bounded keys.

    ``min_value`` (optional, int payload specs only) carries the inclusive lower
    bound the through-model field already declares (its ``MinValueValidator``),
    derived from the model at registration. Consumed by the data-patch adapter so
    an out-of-range payload (e.g. ``count: 0``) fails as a clear ``PatchError`` at
    plan time rather than deferring to the DB CHECK as an opaque ``IntegrityError``
    when the resolver materializes the row. ``None`` for unbounded keys.
    """

    name: str
    scalar_type: type
    required: bool
    nullable: bool = False
    identity: str | None = None
    fk_target: FkTarget | None = None
    display_key: str | None = None
    max_length: int | None = None
    min_value: int | None = None


@dataclass(frozen=True, slots=True)
class RelationshipSchema:
    """Shape of one relationship namespace: value-key list + valid subjects."""

    namespace: str
    value_keys: tuple[ValueKeySpec, ...]
    valid_subjects: frozenset[type[ClaimControlledModel]]


class FkClaim(NamedTuple):
    """A direct FK claim paired with its subject model class.

    Used to carry FK claims from ``validate_claims_batch`` into
    ``validate_fk_claims_batch`` where target existence is checked.
    """

    claim: Claim
    model_class: type[ClaimControlledModel]


class RelationshipTargetKey(NamedTuple):
    """Group key for batched relationship target existence checks."""

    namespace: str
    value_key: str


class FkTarget(NamedTuple):
    """A foreign-key target lookup: ``(model, lookup_field)``.

    Used in two places: ``ValueKeySpec.fk_target`` declares the target of a
    relationship value-key, and ``validate_relationship_claims_batch`` keys
    its per-group existence query by this same pair.
    """

    model: type[models.Model]
    lookup_field: str


class BatchValidationResult(NamedTuple):
    """Return value of :func:`validate_claims_batch`."""

    valid: list[Claim]
    rejected_count: int


class RelationshipClaimRef(NamedTuple):
    """A relationship claim paired with the referenced target value.

    The ``ref`` is the value from the claim's value dict at the spec's
    ``value_key`` (e.g. a person slug or role pk); its concrete type
    depends on the target's lookup field.
    """

    claim: Claim
    ref: object


_relationship_schemas: dict[str, RelationshipSchema] = {}

# Cached frozenset of registered namespace names. Invalidated on every
# ``register_relationship_schema`` call and rebuilt lazily by
# ``get_relationship_namespaces``. Registration happens once during
# ``CatalogConfig.ready()``, so the cache is effectively permanent after
# startup — worth caching because ``get_relationship_namespaces`` is
# called inside per-winner loops during resolve.
_namespaces_cache: frozenset[str] | None = None


def register_relationship_schema(
    namespace: str,
    value_keys: tuple[ValueKeySpec, ...],
    valid_subjects: Iterable[type[ClaimControlledModel]],
) -> None:
    """Register a relationship schema. Idempotent; conflicting re-registration raises.

    Invariants enforced here (not at the validator):
    - ``identity is not None`` ⇒ ``required=True`` on every value-key.
    - ``namespace`` must not collide with a concrete claim-controlled field
      name on any class in ``valid_subjects`` — ensures ``classify_claim``
      step 1 (DIRECT) and step 2 (RELATIONSHIP) never both match for a
      subject the namespace applies to.

    Note: the collision guard only iterates ``valid_subjects``. If a future
    model outside ``valid_subjects`` grows a concrete field matching an
    already-registered namespace, classify step 1 correctly routes it to
    DIRECT for that model; the RELATIONSHIP validator (and its wrong-subject
    check) never sees such claims. That's the intended routing, but it
    means this guard does not protect every (namespace, model) pair — only
    those where the namespace is registered for the subject.
    """
    for spec in value_keys:
        if spec.identity is not None and not spec.required:
            raise ImproperlyConfigured(
                f"namespace {namespace!r}, value_key {spec.name!r}: "
                f"identity keys must be required "
                f"(identity={spec.identity!r}, required=False)"
            )

    # display_key invariants. Naming a sibling spec lets one declaration drive
    # both the resolver (which stores the override into AliasModel.value) and
    # the display engine (which renders identity slots in edit history). The
    # checks below catch malformed declarations at app-ready time.
    specs_by_name = {spec.name: spec for spec in value_keys}
    seen_display_keys: dict[str, str] = {}  # display_key → identity spec name
    for spec in value_keys:
        if spec.display_key is None:
            continue
        if spec.identity is None:
            raise ImproperlyConfigured(
                f"namespace {namespace!r}, value_key {spec.name!r}: "
                f"display_key is only allowed on identity specs"
            )
        target = specs_by_name.get(spec.display_key)
        if target is None:
            raise ImproperlyConfigured(
                f"namespace {namespace!r}, value_key {spec.name!r}: "
                f"display_key {spec.display_key!r} does not name a sibling spec"
            )
        if target.identity is not None:
            raise ImproperlyConfigured(
                f"namespace {namespace!r}, value_key {spec.name!r}: "
                f"display_key target {spec.display_key!r} must be non-identity"
            )
        if target.scalar_type is not spec.scalar_type:
            raise ImproperlyConfigured(
                f"namespace {namespace!r}, value_key {spec.name!r}: "
                f"display_key target {spec.display_key!r} scalar_type "
                f"{target.scalar_type.__name__} must match identity scalar_type "
                f"{spec.scalar_type.__name__}"
            )
        if target.fk_target is not None:
            raise ImproperlyConfigured(
                f"namespace {namespace!r}, value_key {spec.name!r}: "
                f"display_key target {spec.display_key!r} must not declare fk_target"
            )
        prior = seen_display_keys.get(spec.display_key)
        if prior is not None:
            raise ImproperlyConfigured(
                f"namespace {namespace!r}: identity specs {prior!r} and "
                f"{spec.name!r} both declare display_key={spec.display_key!r}"
            )
        seen_display_keys[spec.display_key] = spec.name

    # Lock down the input here so the schema's invariant (immutability) is
    # an internal guarantee, not something callers must satisfy.
    frozen_subjects = frozenset(valid_subjects)
    for subject_model in frozen_subjects:
        if namespace in get_claim_fields(subject_model):
            raise ImproperlyConfigured(
                f"namespace {namespace!r} collides with a concrete claim field "
                f"on {subject_model.__name__}"
            )

    new = RelationshipSchema(
        namespace=namespace,
        value_keys=value_keys,
        valid_subjects=frozen_subjects,
    )
    existing = _relationship_schemas.get(namespace)
    if existing is not None:
        if existing == new:
            return
        raise ImproperlyConfigured(
            f"namespace {namespace!r} already registered with a different schema"
        )
    _relationship_schemas[namespace] = new
    global _namespaces_cache
    _namespaces_cache = None


def get_relationship_schema(namespace: str) -> RelationshipSchema | None:
    """Return the schema for a namespace, or ``None`` if unregistered."""
    return _relationship_schemas.get(namespace)


def get_all_relationship_schemas() -> dict[str, RelationshipSchema]:
    """Return the registry keyed by namespace (read-only snapshot)."""
    return dict(_relationship_schemas)


def get_relationship_namespaces() -> frozenset[str]:
    """Return the cached frozenset of registered namespace names.

    Hot path: called inside per-winner loops during entity resolve. The
    frozenset is rebuilt once after registration (or on first access) and
    reused until another ``register_relationship_schema`` call invalidates it.
    """
    global _namespaces_cache
    if _namespaces_cache is None:
        _namespaces_cache = frozenset(_relationship_schemas)
    return _namespaces_cache


def get_display_override(
    value: Mapping[str, object],
    schema: RelationshipSchema,
    identity_spec_name: str,
) -> object | None:
    """Return the user-facing rendering override for one identity slot, or None.

    Reads ``display_key`` from the identity spec named ``identity_spec_name``;
    if set and the named sibling key has a truthy value in ``value``, returns
    that value. Otherwise returns ``None`` so callers fall back to the
    canonical identity value.

    Truthy semantics match the historical resolver expression
    ``val.get("alias_display") or alias_val`` so empty strings fall through
    to the canonical identity rather than being treated as an override.

    Shared by the catalog alias resolver (which stores the override into
    ``AliasModel.value``) and the provenance display engine (which renders
    the identity slot in edit history).
    """
    spec = next(
        s
        for s in schema.value_keys
        if s.name == identity_spec_name and s.identity is not None
    )
    if spec.display_key is None:
        return None
    candidate = value.get(spec.display_key)
    return candidate if candidate else None


def classify_claim(
    model_class: type[ClaimControlledModel],
    field_name: str,
    claim_key: str,
    value: Any,  # noqa: ANN401 - signature preserved for call-site stability
    *,
    claim_fields: dict[str, str] | None = None,
) -> str:
    """Classify a claim from its ``field_name`` and the registered schemas.

    Returns one of ``DIRECT``, ``RELATIONSHIP``, ``EXTRA``, or
    ``UNRECOGNIZED``.

    - **DIRECT**: ``field_name`` is a concrete claim-controlled Django field.
    - **RELATIONSHIP**: ``field_name`` is a registered relationship namespace.
    - **EXTRA**: neither, but the model has an ``extra_data`` JSONField.
    - **UNRECOGNIZED**: none of the above — likely a typo or stale field name.

    Wrong-subject (namespace registered but this ``model_class`` is not in
    ``valid_subjects``) still routes to ``RELATIONSHIP``; the validator
    rejects it with a clear error.

    Routing precedence is "DIRECT first, then RELATIONSHIP". The registration
    collision guard in ``register_relationship_schema`` prevents both from
    matching at once for any ``model_class`` in the namespace's
    ``valid_subjects``. Outside that set, DIRECT precedence is what keeps
    routing unambiguous — e.g. if a future model grows a concrete field
    matching an already-registered namespace it isn't part of, step 1
    correctly claims the write for DIRECT on that model.

    Pass ``claim_fields`` to avoid repeated ``get_claim_fields()`` calls in
    batch contexts. When omitted, it is computed on each call (fine for
    single-claim use in ``_assert_claim``).
    """
    if claim_fields is None:
        claim_fields = get_claim_fields(model_class)

    if field_name in claim_fields:
        return DIRECT

    if field_name in _relationship_schemas:
        return RELATIONSHIP

    if _has_extra_data(model_class):
        return EXTRA

    return UNRECOGNIZED


def validate_single_relationship_claim(
    *,
    subject_model: type[ClaimControlledModel],
    field_name: str,
    claim_key: str,
    value: Any,  # noqa: ANN401 - claim value is arbitrary JSON
) -> None:
    """Validate one relationship claim's shape. Raises ``ValidationError``.

    Shared by ``_assert_claim`` and ``validate_claims_batch``. Rules are
    applied in a fixed order (see implementation) — each rule assumes its
    predecessors have passed; reordering trades a clean ``ValidationError``
    for a ``TypeError``/``KeyError`` that masks the real problem.
    """
    from apps.provenance.models import make_claim_key

    schema = _relationship_schemas.get(field_name)
    # By invariant, ``classify_claim`` only routes a claim to RELATIONSHIP
    # when the namespace is registered, so a missing schema here means the
    # caller invoked the validator directly with an unknown namespace —
    # a programming error, not a rejectable user input. Surface as such.
    assert schema is not None, (
        f"No relationship schema registered for namespace {field_name!r}"
    )

    # 1. Wrong subject — refuse before checking shape so the error names the
    # routing problem directly.
    if subject_model not in schema.valid_subjects:
        allowed = sorted(m.__name__ for m in schema.valid_subjects)
        raise ValidationError(
            f"Namespace {field_name!r} is not valid on "
            f"{subject_model.__name__}. Allowed subjects: {allowed}."
        )

    # 2. Non-dict value — every remaining rule indexes into `value`.
    if type(value) is not dict:
        raise ValidationError(
            f"Value for {field_name!r} must be a dict, got {type(value).__name__}."
        )

    # 3. Missing / non-bool `exists`. `type(v) is bool` (not isinstance):
    # `isinstance(True, int)` is True, which would let `{"exists": 1}`
    # through on the mirror-image scalar_type=bool rule below.
    if "exists" not in value:
        raise ValidationError(
            f"Value for {field_name!r} missing required 'exists' key."
        )
    if type(value["exists"]) is not bool:
        raise ValidationError(
            f"Value for {field_name!r} 'exists' must be bool, "
            f"got {type(value['exists']).__name__}."
        )

    # 4. Missing any required key. Must precede rule 7 (canonical claim_key),
    # which composes identity parts via `value[spec.name]`.
    for spec in schema.value_keys:
        if spec.required and spec.name not in value:
            raise ValidationError(
                f"Value for {field_name!r} missing required key {spec.name!r}."
            )

    # 5. Wrong scalar type for any present registered key. `type(v) is T`
    # rather than `isinstance(v, T)` rejects `bool` where `int` is expected
    # (PKs, counts) and rejects enum / numpy scalars that would slip past
    # `isinstance`. For `nullable=True`, accept `None` in addition.
    specs_by_name = {spec.name: spec for spec in schema.value_keys}
    for spec in schema.value_keys:
        if spec.name not in value:
            continue
        v = value[spec.name]
        if v is None:
            if not spec.nullable:
                raise ValidationError(
                    f"Value for {field_name!r} key {spec.name!r} may not be null."
                )
            continue
        if type(v) is not spec.scalar_type:
            raise ValidationError(
                f"Value for {field_name!r} key {spec.name!r} must be "
                f"{spec.scalar_type.__name__}, got {type(v).__name__}."
            )

    # 6. Unknown keys (other than "exists" and registered names). Applies
    # uniformly to retractions — a retraction carrying a stale extra key is
    # rejected the same as a positive claim.
    known = {"exists"} | specs_by_name.keys()
    unknown = value.keys() - known
    if unknown:
        raise ValidationError(
            f"Value for {field_name!r} has unknown keys "
            f"{sorted(unknown)!r}. Allowed: {sorted(known)!r}."
        )

    # 7. Non-canonical claim_key. `make_claim_key` sorts its kwargs, so the
    # dict-comprehension order doesn't matter.
    identity_parts = {
        spec.identity: value[spec.name]
        for spec in schema.value_keys
        if spec.identity is not None
    }
    expected_claim_key = make_claim_key(field_name, **identity_parts)
    if claim_key != expected_claim_key:
        raise ValidationError(
            f"claim_key {claim_key!r} for namespace {field_name!r} is "
            f"not canonical; expected {expected_claim_key!r}."
        )


def _has_extra_data(model_class: type[ClaimControlledModel]) -> bool:
    """Check whether a model has a concrete ``extra_data`` field.

    Uses ``_meta`` field introspection rather than ``hasattr`` to avoid
    matching non-field attributes (properties, methods, etc.).
    """
    try:
        # django-stubs validates string-literal field lookups against the
        # model's declared fields. ``extra_data`` is declared on some
        # concrete catalog subclasses (e.g. MachineModel), not on the
        # abstract ``ClaimControlledModel`` we accept here, so the literal
        # lookup type-fails at the base — runtime semantics are correct.
        model_class._meta.get_field("extra_data")  # type: ignore[misc]
        return True
    except FieldDoesNotExist:
        return False


def validate_claim_value(
    field_name: str,
    value: Any,  # noqa: ANN401 - claim value is arbitrary JSON (scalar/dict/list/null)
    model_class: type[ClaimControlledModel],
) -> Any:  # noqa: ANN401 - returns the (possibly coerced) claim value, same shape as input
    """Validate and possibly transform a scalar claim value.

    Returns the (possibly transformed) value on success.
    Raises ``django.core.exceptions.ValidationError`` on failure.

    Validates:
    - Mojibake (encoding corruption)
    - Markdown cross-reference links
    - Type coercion via ``field.to_python()``
    - Django field validator chain (range, URL format, etc.)

    Does NOT validate:
    - Unknown/uneditable field names (request-level concern)
    - Null/blank clearability (request-level concern)
    - FK target existence (see ``validate_fk_claims_batch``)
    """
    from apps.core.markdown import prepare_markdown_claim_value
    from apps.core.validators import validate_no_mojibake

    field = model_class._meta.get_field(field_name)

    # FK fields and reverse relations are validated elsewhere (or not at all).
    # Narrowing to Field also rules out ForeignObjectRel, which lacks
    # validators/blank/to_python/choices.
    if not isinstance(field, models.Field) or field.is_relation:
        return value

    # Mojibake check — subsumes the old step-0 check in the bulk ingest path.
    if isinstance(value, str) and validate_no_mojibake in field.validators:
        validate_no_mojibake(value)

    # Reject whitespace-only strings for required text fields.
    # CharField.to_python() does not strip, so "   " passes through
    # unchallenged.  For blank=False fields, whitespace-only is
    # semantically blank and should be rejected at the claim boundary.
    if isinstance(value, str) and not field.blank and not value.strip():
        raise ValidationError(
            f"Field '{field_name}' cannot be blank (whitespace-only)."
        )

    # Markdown cross-ref conversion (authoring → storage format).
    # Returns value unchanged for non-markdown fields.
    value = prepare_markdown_claim_value(field_name, value, model_class)

    # Type coercion + Django field validators.
    # Always run to_python() for type checking (e.g. BooleanField rejects
    # "maybe"), even on fields with no explicit validators.
    if value != "":
        # JSON has no Decimal type — numeric values arrive as float.
        # to_python(float) produces Decimal with IEEE 754 artifacts
        # (e.g. 8.95 → Decimal('8.950')), which DecimalValidator rejects.
        # Stringify first so to_python("8.95") → Decimal("8.95") cleanly.
        coerce_value = str(value) if isinstance(value, float) else value
        try:
            typed = field.to_python(coerce_value)
        except (ValueError, ValidationError) as exc:
            if isinstance(exc, ValidationError):
                raise
            raise ValidationError(f"Invalid value for '{field_name}': {exc}") from exc
        for validator in field.validators:
            validator(typed)

        # Django's choices validation lives in Field.validate(), not in
        # Field.run_validators().  Check it explicitly so invalid choices
        # (e.g. status='bogus') are caught at the claim boundary.
        if field.choices:
            valid_choices = {k for k, _v in getattr(field, "flatchoices", ())}
            if typed not in valid_choices:
                raise ValidationError(
                    f"Value {value!r} is not a valid choice for "
                    f"'{field_name}'. Valid: {sorted(valid_choices)}"
                )

        # System-wide slug shape (lowercase, single hyphens between segments,
        # no leading/trailing/repeated hyphens). Django's stock
        # ``validate_slug`` is laxer (allows uppercase, underscores, free
        # hyphen placement); apply the strict shared regex so the edit path
        # surfaces the same field-level message as the create path.
        if (
            isinstance(field, models.SlugField)
            and isinstance(typed, str)
            and typed
            and not SLUG_RE.match(typed)
        ):
            raise ValidationError(SLUG_FORMAT_MESSAGE)

    return value


def validate_claims_batch(
    pending_claims: list[Claim],
) -> BatchValidationResult:
    """Validate claims in batch mode.

    Invalid claims are logged and removed from the list.
    Valid scalar claims may have transformed values (e.g. markdown link
    conversion written back to ``claim.value``).

    Uses ``classify_claim`` to classify each claim structurally, then:

    - **DIRECT** scalar → validate via ``validate_claim_value()``
    - **DIRECT** FK → collect for ``validate_fk_claims_batch()``
    - **RELATIONSHIP** → collect for ``validate_relationship_claims_batch()``
    - **EXTRA** → pass through (free-form staging data)
    - **UNRECOGNIZED** → reject with warning
    """
    from django.contrib.contenttypes.models import ContentType

    rejected: list[Claim] = []
    fk_claims: list[FkClaim] = []
    rel_claims: list[Claim] = []

    # Cache model_class and claim_fields per content_type_id.
    model_cache: dict[int, type[ClaimControlledModel]] = {}
    fields_cache: dict[int, dict[str, str]] = {}

    for claim in pending_claims:
        ct_id = claim.content_type_id

        if ct_id not in model_cache:
            model_class = ContentType.objects.get_for_id(ct_id).model_class()
            if model_class is None or not issubclass(model_class, ClaimControlledModel):
                logger.warning(
                    "Rejected claim for unknown or non-claim-controlled "
                    "content type id %s (object_id=%s)",
                    ct_id,
                    claim.object_id,
                )
                rejected.append(claim)
                # NB: we deliberately do not write model_cache[ct_id] /
                # fields_cache[ct_id] on the rejection path. Subsequent claims
                # with the same ct_id will re-check and re-reject; that's
                # correct — we never want a poisoned ct_id to silently
                # short-circuit later iterations as if it were resolved.
                continue
            model_cache[ct_id] = model_class
            fields_cache[ct_id] = get_claim_fields(model_cache[ct_id])

        model_class = model_cache[ct_id]
        fn = claim.field_name

        ct = classify_claim(
            model_class,
            fn,
            claim.claim_key,
            claim.value,
            claim_fields=fields_cache[ct_id],
        )

        if ct == RELATIONSHIP:
            try:
                validate_single_relationship_claim(
                    subject_model=model_class,
                    field_name=fn,
                    claim_key=claim.claim_key,
                    value=claim.value,
                )
            except ValidationError as exc:
                logger.warning(
                    "Rejected relationship claim %s.%s (object_id=%s): %s",
                    model_class.__name__,
                    fn,
                    claim.object_id,
                    "; ".join(exc.messages),
                )
                rejected.append(claim)
                continue
            rel_claims.append(claim)
            continue
        if ct == EXTRA:
            continue
        if ct == UNRECOGNIZED:
            logger.warning(
                "Rejected claim with unrecognized field_name %r on %s (object_id=%s)",
                fn,
                model_class.__name__,
                claim.object_id,
            )
            rejected.append(claim)
            continue

        # DIRECT — determine scalar vs FK.
        field = model_class._meta.get_field(fn)
        if field.is_relation:
            fk_claims.append(FkClaim(claim, model_class))
            continue

        # Scalar — validate value.
        try:
            claim.value = validate_claim_value(fn, claim.value, model_class)
        except ValidationError as exc:
            logger.warning(
                "Rejected invalid claim %s.%s (object_id=%s): %s",
                model_class.__name__,
                fn,
                claim.object_id,
                "; ".join(exc.messages),
            )
            rejected.append(claim)

    # Batch FK validation.
    if fk_claims:
        rejected.extend(validate_fk_claims_batch(fk_claims))

    # Batch relationship target validation.
    if rel_claims:
        rejected.extend(validate_relationship_claims_batch(rel_claims))

    rejected_set = {id(c) for c in rejected}
    valid = [c for c in pending_claims if id(c) not in rejected_set]
    return BatchValidationResult(valid, len(rejected))


def validate_fk_claims_batch(
    fk_claims: list[FkClaim],
) -> list[Claim]:
    """Batch-validate FK scalar claims. Returns list of rejected claims.

    Groups claims by ``(model_class, field_name)``, then issues one query
    per group to check target existence. Mirrors the ``claim_fk_lookups``
    convention from the resolver.
    """
    groups: dict[
        tuple[type[ClaimControlledModel], str],
        list[Claim],
    ] = defaultdict(list)
    for fk in fk_claims:
        groups[(fk.model_class, fk.claim.field_name)].append(fk.claim)

    rejected: list[Claim] = []
    for (model_class, field_name), group in groups.items():
        field = model_class._meta.get_field(field_name)
        target_model = field.related_model
        assert isinstance(target_model, type)
        assert issubclass(target_model, models.Model)
        target_manager = target_model._default_manager
        lookup_key = model_class.claim_fk_lookups.get(field_name, "slug")

        # Collect all non-empty slug values, keyed by claim identity.
        slug_by_claim: dict[int, str] = {}
        for claim in group:
            v = claim.value
            if v is not None and v != "":
                slug_by_claim[id(claim)] = str(v).strip()

        slugs = set(slug_by_claim.values())
        if not slugs:
            continue

        existing = set(
            target_manager.filter(**{f"{lookup_key}__in": slugs}).values_list(
                lookup_key, flat=True
            )
        )

        for claim in group:
            slug = slug_by_claim.get(id(claim))
            if slug is None:
                continue
            if slug not in existing:
                logger.warning(
                    "Rejected FK claim %s.%s (object_id=%s): "
                    "target %s with %s=%r does not exist",
                    model_class.__name__,
                    field_name,
                    claim.object_id,
                    target_model.__name__,
                    lookup_key,
                    slug,
                )
                rejected.append(claim)

    return rejected


def validate_relationship_claims_batch(
    rel_claims: list[Claim],
) -> list[Claim]:
    """Batch-validate relationship claim targets. Returns list of rejected claims.

    Groups claims by ``(namespace, value_key)``, then issues one existence
    query per group — the same grouped-query pattern used by
    ``validate_fk_claims_batch`` for FK claims.

    Reads target models from ``ValueKeySpec.fk_target`` on each registered
    schema. Non-FK value-keys (literals like ``alias_value``) have
    ``fk_target=None`` and pass through without an existence check.
    Unregistered namespaces also pass through.
    """
    if not _relationship_schemas:
        return []

    groups: dict[RelationshipTargetKey, list[RelationshipClaimRef]] = defaultdict(list)
    group_meta: dict[RelationshipTargetKey, FkTarget] = {}

    for claim in rel_claims:
        namespace = claim.field_name
        schema = _relationship_schemas.get(namespace)
        if schema is None:
            continue
        value = claim.value
        if not isinstance(value, dict):
            continue
        # Retractions (exists=False) don't need target validation — the
        # target may have been deleted, and the claim is being removed.
        if not member_is_present(claim):
            continue
        for spec in schema.value_keys:
            if spec.fk_target is None:
                continue
            ref = value.get(spec.name)
            if ref is None:
                continue
            key = RelationshipTargetKey(namespace, spec.name)
            groups[key].append(RelationshipClaimRef(claim, ref))
            if key not in group_meta:
                group_meta[key] = spec.fk_target

    rejected: list[Claim] = []
    rejected_ids: set[int] = set()

    for key, group in groups.items():
        target = group_meta[key]
        namespace = key.namespace

        refs = {r.ref for r in group}
        existing = set(
            target.model._default_manager.filter(
                **{f"{target.lookup_field}__in": refs}
            ).values_list(target.lookup_field, flat=True)
        )

        for r in group:
            if r.ref not in existing and id(r.claim) not in rejected_ids:
                logger.warning(
                    "Rejected relationship claim %s (object_id=%s): "
                    "target %s with %s=%r does not exist",
                    r.claim.claim_key or namespace,
                    r.claim.object_id,
                    target.model.__name__,
                    target.lookup_field,
                    r.ref,
                )
                rejected.append(r.claim)
                rejected_ids.add(id(r.claim))

    return rejected
