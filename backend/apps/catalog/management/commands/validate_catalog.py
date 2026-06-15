"""Post-ingestion catalog validation.

Checks the resolved catalog for data quality issues: missing fields,
broken references, duplicate entities, unresolved claims, and structural
invariant violations. Intended to run after ``resolve_claims``.

Exit codes:
  0 — no errors (warnings may be present)
  1 — errors found
"""

from __future__ import annotations

import json
import logging
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple, cast

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandParser
from django.db.models import Count, F, Model, Q
from django.db.models.functions import Lower

from apps.catalog.models import (
    CatalogModel,
    Credit,
    CreditRole,
    GameplayFeature,
    MachineModel,
    Manufacturer,
    Person,
    Tag,
    Theme,
    Title,
)
from apps.provenance.claim_ranking_in_db import ranked_claims
from apps.provenance.models import Claim

logger = logging.getLogger(__name__)


def _winning_claims(content_type: ContentType, field_name: str) -> list[Claim]:
    """Pick the winning claim per (object_id, claim_key) for a field.

    Uses the shared :func:`~apps.provenance.claim_ranking_in_db.ranked_claims` so
    this validator picks exactly what the resolver materializes — highest
    source/user priority, newest ``created_at``, then highest pk (last write),
    and disabled sources excluded.  Only the winning claim per claim_key per
    object is returned.
    """
    claims = ranked_claims(
        Claim.objects.filter(content_type=content_type, field_name=field_name),
        "object_id",
        "claim_key",
    )

    winners: list[Claim] = []
    seen: set[tuple[int, str]] = set()
    for claim in claims:
        key = (claim.object_id, claim.claim_key)
        if key not in seen:
            seen.add(key)
            winners.append(claim)
    return winners


# Default location for golden records. Overridden in tests via monkeypatch.
GOLDEN_RECORDS_PATH = (
    Path(__file__).resolve().parents[2] / "fixtures" / "golden_records.json"
)


@dataclass
class ValidationResult:
    """Accumulates validation findings."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def note(self, msg: str) -> None:
        self.info.append(msg)


def check_nameless_models(result: ValidationResult) -> None:
    """Every MachineModel must have a name after resolution."""
    nameless = MachineModel.objects.filter(Q(name="") | Q(name__isnull=True))
    count = nameless.count()
    if count:
        result.error(f"{count} machine model(s) have no name after resolution")
        for pm in nameless[:10]:
            result.error(
                f"  pk={pm.pk} slug={pm.slug!r} ipdb_id={pm.ipdb_id} opdb_id={pm.opdb_id}"
            )
        if count > 10:
            result.error(f"  ... and {count - 10} more")


def check_titleless_models(result: ValidationResult) -> None:
    """Every MachineModel must have a Title — enforced by the DB NOT NULL.

    This is a defense-in-depth check: the FK is NOT NULL, so any hit here
    indicates a constraint bypass (raw SQL, migration issue) and must be
    fixed before the row leaks into the resolved catalog.
    """
    titleless = MachineModel.objects.filter(title__isnull=True)
    count = titleless.count()
    if count:
        result.error(f"{count} machine model(s) have no title")
        for pm in titleless[:10]:
            result.error(
                f"  pk={pm.pk} slug={pm.slug!r} ipdb_id={pm.ipdb_id} opdb_id={pm.opdb_id}"
            )
        if count > 10:
            result.error(f"  ... and {count - 10} more")


def check_nameless_titles(result: ValidationResult) -> None:
    """Every Title must have a name."""
    nameless = Title.objects.filter(Q(name="") | Q(name__isnull=True))
    count = nameless.count()
    if count:
        result.error(f"{count} title(s) have no name after resolution")
        for t in nameless[:10]:
            result.error(f"  pk={t.pk} slug={t.slug!r} opdb_id={t.opdb_id}")


def check_nameless_persons(result: ValidationResult) -> None:
    """Every Person must have a name."""
    nameless = Person.objects.filter(Q(name="") | Q(name__isnull=True))
    count = nameless.count()
    if count:
        result.error(f"{count} person(s) have no name after resolution")
        for p in nameless[:10]:
            result.error(f"  pk={p.pk} slug={p.slug!r}")


def check_self_referential_variant(result: ValidationResult) -> None:
    """variant_of and converted_from must not point to self."""
    self_variant = MachineModel.objects.filter(variant_of=F("pk"))
    for pm in self_variant:
        result.error(
            f"Model {pm.name!r} (pk={pm.pk}) has variant_of pointing to itself"
        )

    self_converted = MachineModel.objects.filter(converted_from=F("pk"))
    for pm in self_converted:
        result.error(
            f"Model {pm.name!r} (pk={pm.pk}) has converted_from pointing to itself"
        )


def check_variant_chains(result: ValidationResult) -> None:
    """variant_of should be 1-hop max (no chains)."""
    chains = MachineModel.objects.filter(
        variant_of__isnull=False,
        variant_of__variant_of__isnull=False,
    )
    count = chains.count()
    if count:
        result.warn(f"{count} model(s) form variant_of chains (more than 1 hop)")
        for pm in chains[:10]:
            parent = pm.variant_of
            assert parent is not None
            grandparent = parent.variant_of
            assert grandparent is not None
            result.warn(
                f"  {pm.name!r} (pk={pm.pk}) → {parent.slug!r} → {grandparent.slug!r}"
            )
        if count > 10:
            result.warn(f"  ... and {count - 10} more")


def check_duplicate_persons(result: ValidationResult) -> None:
    """Flag persons with the same lowercased name."""
    dupes = (
        Person.objects.annotate(lower_name=Lower("name"))
        .values("lower_name")
        .annotate(cnt=Count("id"))
        .filter(cnt__gt=1)
        .order_by("-cnt")
    )
    count = dupes.count()
    if count:
        result.warn(f"{count} person name(s) appear more than once (case-insensitive)")
        # django-stubs types chained .values().annotate() rows as
        # AnnotatedWith[TypedDict] (non-indexable Person), but at runtime each
        # row is a plain dict. Cast to the real shape at the iteration boundary.
        for d in cast("list[dict[str, Any]]", list(dupes[:10])):
            persons = Person.objects.filter(name__iexact=d["lower_name"])
            slugs = ", ".join(p.slug for p in persons)
            result.warn(f"  {d['lower_name']!r} (×{d['cnt']}): {slugs}")
        if count > 10:
            result.warn(f"  ... and {count - 10} more")


def check_duplicate_manufacturers(result: ValidationResult) -> None:
    """Flag manufacturers with the same lowercased name."""
    dupes = (
        Manufacturer.objects.annotate(lower_name=Lower("name"))
        .values("lower_name")
        .annotate(cnt=Count("id"))
        .filter(cnt__gt=1)
        .order_by("-cnt")
    )
    count = dupes.count()
    if count:
        result.warn(
            f"{count} manufacturer name(s) appear more than once (case-insensitive)"
        )
        # See note in check_duplicate_persons: chained .values().annotate()
        # rows are dicts at runtime but mistyped by django-stubs.
        for d in cast("list[dict[str, Any]]", list(dupes[:10])):
            mfrs = Manufacturer.objects.filter(name__iexact=d["lower_name"])
            slugs = ", ".join(m.slug for m in mfrs)
            result.warn(f"  {d['lower_name']!r} (×{d['cnt']}): {slugs}")


def check_models_without_corporate_entity(result: ValidationResult) -> None:
    """Models without a corporate entity are likely ingestion gaps."""
    count = MachineModel.objects.filter(corporate_entity__isnull=True).count()
    if count:
        result.warn(f"{count} model(s) have no corporate entity")


def check_models_without_year(result: ValidationResult) -> None:
    """Models without a year."""
    count = MachineModel.objects.filter(year__isnull=True).count()
    if count:
        result.note(f"{count} model(s) have no year")


def check_titles_needing_review(result: ValidationResult) -> None:
    """Auto-generated titles flagged for review."""
    count = Title.objects.filter(needs_review=True).count()
    if count:
        result.note(f"{count} title(s) flagged for review")


def check_orphan_claims(result: ValidationResult) -> None:
    """Active claims whose target entity no longer exists."""
    # Check each content type that has claims.
    ct_counts: Counter[str] = Counter()
    for ct_id, obj_id in (
        Claim.objects.filter(is_active=True)
        .values_list("content_type_id", "object_id")
        .distinct()
    ):
        ct = ContentType.objects.get_for_id(ct_id)
        model_class = ct.model_class()
        if model_class is None:
            ct_counts[f"unknown-ct-{ct_id}"] += 1
            continue
        if not model_class._default_manager.filter(pk=obj_id).exists():
            ct_counts[ct.model] += 1

    total = sum(ct_counts.values())
    if total:
        result.warn(f"{total} active claim(s) reference deleted entities")
        for model_name, cnt in ct_counts.most_common():
            result.warn(f"  {model_name}: {cnt}")


def check_unresolved_fk_claims(result: ValidationResult) -> None:
    """Active FK claims that reference slugs with no matching target.

    This catches cases where ingestion asserted a claim like
    manufacturer=some-slug but no Manufacturer with that slug exists.
    """
    from apps.provenance.models import get_claim_fields

    ct = ContentType.objects.get_for_model(MachineModel)
    claim_fields = get_claim_fields(MachineModel)
    fk_lookups_map = MachineModel.claim_fk_lookups

    for field_name in claim_fields:
        field = MachineModel._meta.get_field(field_name)
        if not field.is_relation:
            continue

        target_model = field.related_model
        if target_model is None:
            continue
        assert isinstance(target_model, type)
        assert issubclass(target_model, Model)
        lookup_key = fk_lookups_map.get(field_name, "slug")

        # Get winning claim values for this field (one per object+claim_key).
        winners = _winning_claims(ct, field_name)
        if not winners:
            continue

        active_values = {c.value for c in winners}

        # Get all valid lookup keys.
        valid_keys = set(
            target_model._default_manager.values_list(lookup_key, flat=True)
        )

        unresolved = set()
        for v in active_values:
            key = str(v).strip() if v else ""
            if key and key not in valid_keys:
                unresolved.add(key)

        if unresolved:
            result.warn(f"{len(unresolved)} unresolved {field_name} claim value(s)")
            for slug in sorted(unresolved)[:5]:
                result.warn(f"  {slug!r}")
            if len(unresolved) > 5:
                result.warn(f"  ... and {len(unresolved) - 5} more")


def check_unresolved_credit_claims(result: ValidationResult) -> None:
    """Credit claims referencing persons or roles that don't exist."""
    ct = ContentType.objects.get_for_model(MachineModel)
    person_pks = set(Person.objects.values_list("pk", flat=True))
    role_pks = set(CreditRole.objects.values_list("pk", flat=True))

    missing_persons: set[int] = set()
    missing_roles: set[int] = set()

    for claim in _winning_claims(ct, "credit"):
        val = claim.value
        if not isinstance(val, dict):
            continue
        ps = val.get("person")
        if ps is not None and ps not in person_pks:
            missing_persons.add(ps)
        role = val.get("role")
        if role is not None and role not in role_pks:
            missing_roles.add(role)

    if missing_persons:
        result.warn(
            f"{len(missing_persons)} credit claim(s) reference missing person PKs"
        )
        for s in sorted(missing_persons)[:5]:
            result.warn(f"  {s!r}")
        if len(missing_persons) > 5:
            result.warn(f"  ... and {len(missing_persons) - 5} more")

    if missing_roles:
        result.warn(f"{len(missing_roles)} credit claim(s) reference missing role PKs")
        for s in sorted(missing_roles):
            result.warn(f"  {s!r}")


class _M2mCheck(NamedTuple):
    """Config for scanning one M2M claim field for missing target PKs."""

    field_name: str
    pk_key: str
    model_class: type[CatalogModel]


def check_unresolved_m2m_claims(result: ValidationResult) -> None:
    """Theme/tag/gameplay_feature claims referencing PKs that don't exist."""
    ct = ContentType.objects.get_for_model(MachineModel)

    checks: list[_M2mCheck] = [
        _M2mCheck("theme", "theme", Theme),
        _M2mCheck("tag", "tag", Tag),
        _M2mCheck("gameplay_feature", "gameplay_feature", GameplayFeature),
    ]

    for check in checks:
        valid_pks = set(check.model_class._default_manager.values_list("pk", flat=True))

        missing: set[int] = set()
        for claim in _winning_claims(ct, check.field_name):
            val = claim.value
            if not isinstance(val, dict):
                continue
            ref = val.get(check.pk_key)
            if ref is not None and ref not in valid_pks:
                missing.add(ref)

        if missing:
            result.warn(
                f"{len(missing)} {check.field_name} claim(s) reference missing PKs"
            )
            for s in sorted(missing)[:5]:
                result.warn(f"  {s!r}")
            if len(missing) > 5:
                result.warn(f"  ... and {len(missing) - 5} more")


class _CreditKey(NamedTuple):
    """Identity of a materialized credit row: (model, person, role) PKs."""

    model_pk: int
    person_pk: int
    role_pk: int


def check_credits_without_matching_claims(result: ValidationResult) -> None:
    """Credit rows that have no corresponding active claim (stale materialization)."""
    ct = ContentType.objects.get_for_model(MachineModel)

    # Build set of (model_pk, person_pk, role_pk) from active credit claims.
    claimed: set[_CreditKey] = set()
    for claim in Claim.objects.filter(
        content_type=ct, is_active=True, field_name="credit"
    ):
        val = claim.value
        if not isinstance(val, dict) or not val.get("exists", True):
            continue
        person_pk = val.get("person")
        role_pk = val.get("role")
        if person_pk is not None and role_pk is not None:
            claimed.add(_CreditKey(claim.object_id, person_pk, role_pk))

    stale_count = 0
    for credit in Credit.objects.filter(model__isnull=False):
        # filter excludes null model_id; the assertion narrows for mypy.
        assert credit.model_id is not None
        key = _CreditKey(credit.model_id, credit.person_id, credit.role_id)
        if key not in claimed:
            stale_count += 1

    if stale_count:
        result.note(
            f"{stale_count} materialized credit(s) have no matching active claim "
            "(may be from series credits or manual edits)"
        )


def check_uncurated_themes(result: ValidationResult) -> None:
    """Themes that were auto-created during ingestion (no flipcommons-catalog source claim)."""
    from apps.provenance.models import Source

    flipcommons_catalog = Source.objects.filter(slug="flipcommons-catalog").first()
    if not flipcommons_catalog:
        return

    ct = ContentType.objects.get_for_model(Theme)
    curated_theme_ids = set(
        Claim.objects.filter(
            content_type=ct,
            source=flipcommons_catalog,
            field_name="name",
            is_active=True,
        ).values_list("object_id", flat=True)
    )

    uncurated = Theme.objects.exclude(pk__in=curated_theme_ids)
    count = uncurated.count()
    if count:
        result.note(
            f"{count} theme(s) were auto-created (no flipcommons-catalog name claim)"
        )
        for t in uncurated.order_by("name")[:10]:
            result.note(f"  {t.slug!r} ({t.name})")
        if count > 10:
            result.note(f"  ... and {count - 10} more")


def check_summary_stats(result: ValidationResult) -> None:
    """Emit summary counts as info for context."""
    result.note(f"Models: {MachineModel.objects.count()}")
    result.note(f"Titles: {Title.objects.count()}")
    result.note(f"Manufacturers: {Manufacturer.objects.count()}")
    result.note(f"Persons: {Person.objects.count()}")
    result.note(f"Credits: {Credit.objects.filter(model__isnull=False).count()}")
    result.note(f"Themes: {Theme.objects.count()}")
    result.note(f"Active claims: {Claim.objects.filter(is_active=True).count()}")


def check_golden_records(result: ValidationResult) -> None:
    """Verify well-known records match expected values after ingestion.

    Loads assertions from data/golden_records.json and checks each one
    against the resolved catalog. Missing records and field mismatches
    are errors — if a well-known machine is wrong, something broke.
    """
    golden_path = GOLDEN_RECORDS_PATH
    if not golden_path.exists():
        result.error("golden_records.json not found — cannot verify catalog integrity")
        return

    data = json.loads(golden_path.read_text())
    failures = 0

    # --- Models ---
    for entry in data.get("models", []):
        slug = entry["slug"]
        expect = entry["expect"]
        pm = MachineModel.objects.filter(slug=slug).first()
        if pm is None:
            result.error(f"Golden record model {slug!r} not found")
            failures += 1
            continue

        for field_name, expected in expect.items():
            actual = _get_golden_field(pm, field_name)
            if actual != expected:
                result.error(
                    f"Golden record model {slug!r}: "
                    f"{field_name}={actual!r}, expected {expected!r}"
                )
                failures += 1

    # --- Titles ---
    for entry in data.get("titles", []):
        slug = entry["slug"]
        expect = entry["expect"]
        title = Title.objects.filter(slug=slug).first()
        if title is None:
            result.error(f"Golden record title {slug!r} not found")
            failures += 1
            continue

        for field_name, expected in expect.items():
            actual = _get_golden_field(title, field_name)
            if actual != expected:
                result.error(
                    f"Golden record title {slug!r}: "
                    f"{field_name}={actual!r}, expected {expected!r}"
                )
                failures += 1

    # --- Manufacturers ---
    for entry in data.get("manufacturers", []):
        slug = entry["slug"]
        expect = entry["expect"]
        mfr = Manufacturer.objects.filter(slug=slug).first()
        if mfr is None:
            result.error(f"Golden record manufacturer {slug!r} not found")
            failures += 1
            continue

        for field_name, expected in expect.items():
            actual = _get_golden_field(mfr, field_name)
            if actual != expected:
                result.error(
                    f"Golden record manufacturer {slug!r}: "
                    f"{field_name}={actual!r}, expected {expected!r}"
                )
                failures += 1

    if failures:
        result.error(f"{failures} golden record assertion(s) failed")
    else:
        checked = (
            len(data.get("models", []))
            + len(data.get("titles", []))
            + len(data.get("manufacturers", []))
        )
        result.note(f"All {checked} golden record(s) passed")


def _get_golden_field(obj: Model, field_name: str) -> object:
    """Extract a field value from a model instance for golden record comparison.

    Handles FK slug lookups (e.g., manufacturer_slug → obj.manufacturer.slug).
    """
    if field_name.endswith("_slug"):
        # FK slug: e.g., "manufacturer_slug" → obj.manufacturer.slug
        fk_attr = field_name.removesuffix("_slug")
        related = getattr(obj, fk_attr, None)
        return related.slug if related is not None else None
    return getattr(obj, field_name, None)


# Registry of all checks, in execution order.
ALL_CHECKS = [
    check_summary_stats,
    check_golden_records,
    check_nameless_models,
    check_titleless_models,
    check_nameless_titles,
    check_nameless_persons,
    check_self_referential_variant,
    check_variant_chains,
    check_duplicate_persons,
    check_duplicate_manufacturers,
    check_models_without_corporate_entity,
    check_models_without_year,
    check_titles_needing_review,
    check_orphan_claims,
    check_unresolved_fk_claims,
    check_unresolved_credit_claims,
    check_unresolved_m2m_claims,
    check_credits_without_matching_claims,
    check_uncurated_themes,
]


class Command(BaseCommand):
    help = "Validate the resolved catalog for data quality issues."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--fail-on-warn",
            action="store_true",
            help="Exit with code 1 if warnings are found (not just errors).",
        )

    def handle(self, *args: Any, **options: Any) -> None:  # noqa: ANN401  # argparse-driven
        result = ValidationResult()

        for check_fn in ALL_CHECKS:
            check_fn(result)

        # Print results grouped by severity.
        if result.info:
            self.stdout.write(self.style.MIGRATE_HEADING("Info:"))
            for msg in result.info:
                self.stdout.write(f"  {msg}")

        if result.warnings:
            self.stdout.write(self.style.WARNING("Warnings:"))
            for msg in result.warnings:
                self.stdout.write(self.style.WARNING(f"  {msg}"))

        if result.errors:
            self.stdout.write(self.style.ERROR("Errors:"))
            for msg in result.errors:
                self.stdout.write(self.style.ERROR(f"  {msg}"))

        # Summary line.
        self.stdout.write("")
        self.stdout.write(
            f"Validation complete: {len(result.errors)} error(s), "
            f"{len(result.warnings)} warning(s), {len(result.info)} info."
        )

        if result.errors:
            sys.exit(1)
        if options["fail_on_warn"] and result.warnings:
            sys.exit(1)
