"""IPDB source adapter: parse, reconcile, collect claims → IngestPlan.

Converts IPDB JSON data into an IngestPlan for the apply layer.
No database writes — all mutations happen in apply_plan().

The adapter handles:
- Matching IPDB records to existing MachineModels (by ipdb_id); unmatched
  records abort ingest (pindata is the authoritative superset of machines)
- CorporateEntity reconciliation (by IPDB mfr ID, then name/alias)
- Person and Theme reconciliation and creation
- Collecting scalar and relationship claims as PlannedClaimAssert
- Feature/reward/theme/credit extraction from IPDB fields
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from html import unescape
from typing import Any, NamedTuple

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import CommandError

from apps.catalog.claims import build_relationship_claim
from apps.catalog.ingestion.bulk_utils import (
    ManufacturerResolver,
    generate_unique_slug,
)
from apps.catalog.ingestion.constants import IPDB_SKIP_MANUFACTURER_IDS
from apps.catalog.ingestion.ipdb.features import (
    GameplayFeaturePair,
    extract_ipdb_gameplay_features,
    extract_ipdb_reward_types,
    load_mpu_to_system_slug,
    normalize_theme_key,
    parse_ipdb_themes,
    validate_narrative_slugs,
)
from apps.catalog.ingestion.ipdb.records import IpdbRecord
from apps.catalog.ingestion.parsers import (
    _IPDBLocationLookup,
    get_ipdb_location,
    parse_credit_string,
    parse_ipdb_date,
    parse_ipdb_machine_type,
    parse_ipdb_manufacturer_string,
)
from apps.catalog.ingestion.person_lookup import build_person_lookup
from apps.catalog.ingestion.plan import (
    Handle,
    IngestPlan,
    PlannedClaimAssert,
    PlannedEntityCreate,
)
from apps.catalog.ingestion.vocabulary import (
    build_feature_slug_map,
    build_reward_type_map,
)
from apps.catalog.models import (
    CorporateEntity,
    CorporateEntityAlias,
    CorporateEntityLocation,
    CreditRole,
    GameplayFeature,
    MachineModel,
    Person,
    RewardType,
    Theme,
)
from apps.catalog.resolve import (
    resolve_all_credits,
    resolve_all_gameplay_features,
    resolve_all_model_abbreviations,
    resolve_all_reward_types,
    resolve_all_themes,
)
from apps.core.types import ClaimTarget
from apps.provenance.models import Source

logger = logging.getLogger(__name__)

# IpdbRecord attribute → Claim field_name for direct/extra_data claims.
# IPDB never asserts a "name" claim — pindata is the authoritative source
# for machine names, and IPDB titles are frequently encoding-damaged.
CLAIM_FIELDS = {
    "ipdb_id": "ipdb_id",
    "players": "player_count",
    "production_number": "production_quantity",
    "average_fun_rating": "ipdb_rating",
    # Extra data (no dedicated column) — namespaced by source
    "notable_features": "ipdb.notable_features",
    "notes": "ipdb.notes",
    "toys": "ipdb.toys",
    "marketing_slogans": "ipdb.marketing_slogans",
    "model_number": "ipdb.model_number",
}

# IpdbRecord attribute → Credit role slug.
CREDIT_FIELDS = {
    "design_by": "design",
    "art_by": "art",
    "dots_animation_by": "animation",
    "mechanics_by": "mechanics",
    "music_by": "music",
    "sound_by": "sound",
    "software_by": "software",
}


# ---------------------------------------------------------------------------
# Reconciliation result
# ---------------------------------------------------------------------------


@dataclass
class MatchResult:
    """An IPDB record paired with the existing MachineModel it reconciled to."""

    model: MachineModel
    record: IpdbRecord


class CreditQueueEntry(NamedTuple):
    """A credit extracted from one IPDB record, pending person resolution.

    ``content_type_id`` / ``object_id`` identify the MachineModel that
    will receive the credit claim once the person row resolves.
    """

    content_type_id: int
    object_id: int
    name: str
    role_slug: str


class ThemeQueueEntry(NamedTuple):
    """One MachineModel's theme slugs, pending Theme dedup + creation."""

    target: ClaimTarget
    slugs: list[str]


class GameplayFeatureQueueEntry(NamedTuple):
    """One MachineModel's gameplay-feature pairs, pending claim emission."""

    target: ClaimTarget
    pairs: list[GameplayFeaturePair]


class RewardTypeQueueEntry(NamedTuple):
    """One MachineModel's reward-type slugs, pending claim emission."""

    target: ClaimTarget
    slugs: list[str]


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def build_ipdb_plan(
    records: list[IpdbRecord],
    source: Source,
    input_fingerprint: str,
) -> IngestPlan:
    """Build an IngestPlan from parsed IPDB records.

    The adapter is non-mutating — all DB reads are lookups, all writes
    are deferred to ``apply_plan()``.
    """
    ct_mm = ContentType.objects.get_for_model(MachineModel).pk
    ct_ce = ContentType.objects.get_for_model(CorporateEntity).pk
    ct_person = ContentType.objects.get_for_model(Person).pk
    ct_theme = ContentType.objects.get_for_model(Theme).pk

    # ── Step 1: Setup ────────────────────────────────────────────
    feature_map = build_feature_slug_map()
    reward_map = build_reward_type_map()
    mpu_to_slug = load_mpu_to_system_slug()

    # Validate narrative pattern slugs.
    all_vocab_slugs = set(feature_map.values()) | set(reward_map.values())
    bad = validate_narrative_slugs(all_vocab_slugs)
    if bad:
        raise CommandError(
            f"Narrative feature pattern slug(s) not found in catalog vocabulary: "
            f"{', '.join(bad)}\n"
            "Update _NARRATIVE_FEATURE_PATTERNS to use valid slugs."
        )

    # Vocabulary slug→PK lookups.
    feature_slug_to_pk = dict(GameplayFeature.objects.values_list("slug", "pk"))
    reward_slug_to_pk = dict(RewardType.objects.values_list("slug", "pk"))
    role_slug_to_pk = dict(CreditRole.objects.values_list("slug", "pk"))

    # Manufacturer resolver (lookup-only — never auto-create).
    resolver = ManufacturerResolver()

    # CE lookups.
    all_ces = list(CorporateEntity.objects.select_related("manufacturer").all())
    ce_by_ipdb_id: dict[int, CorporateEntity] = {
        ce.ipdb_manufacturer_id: ce
        for ce in all_ces
        if ce.ipdb_manufacturer_id is not None
    }
    ce_by_name: dict[str, CorporateEntity] = {ce.name.lower(): ce for ce in all_ces}
    for alias in CorporateEntityAlias.objects.select_related(
        "corporate_entity__manufacturer"
    ).all():
        key = alias.value.lower()
        if key not in ce_by_name:
            ce_by_name[key] = alias.corporate_entity
    ce_slugs: set[str] = {ce.slug for ce in all_ces}

    # Location validation (existing CEs only).
    location_lookup = _IPDBLocationLookup()
    ce_location_paths: dict[int, set[str]] = {}
    for cel in CorporateEntityLocation.objects.select_related("location").all():
        ce_location_paths.setdefault(cel.corporate_entity_id, set()).add(
            cel.location.location_path
        )

    # Person lookup.
    person_lookup = build_person_lookup()
    person_slugs: set[str] = set(Person.objects.values_list("slug", flat=True))

    # Theme lookup.
    themes_qs = list(Theme.objects.prefetch_related("aliases").all())
    theme_by_slug: dict[str, Theme] = {t.slug: t for t in themes_qs}
    theme_name_lookup: dict[str, str] = {}
    for _t in themes_qs:
        theme_name_lookup[normalize_theme_key(_t.name)] = _t.slug
        for _alias in _t.aliases.all():
            theme_name_lookup.setdefault(normalize_theme_key(_alias.value), _t.slug)

    # Build the plan.
    plan = IngestPlan(
        source=source,
        input_fingerprint=input_fingerprint,
        records_parsed=len(records),
    )

    # Register resolve hooks for MachineModel.
    plan.resolve_hooks[ct_mm] = [
        resolve_all_credits,
        resolve_all_themes,
        resolve_all_gameplay_features,
        resolve_all_reward_types,
        resolve_all_model_abbreviations,
    ]

    # ── Step 2: Reconcile MachineModels ──────────────────────────
    existing_by_ipdb: dict[int, MachineModel] = {
        ipdb_id: pm
        for pm in MachineModel.objects.filter(ipdb_id__isnull=False)
        if (ipdb_id := pm.ipdb_id) is not None
    }

    match_results: list[MatchResult] = []
    unmatched_records: list[tuple[int, str]] = []

    for rec in records:
        if not rec.ipdb_id:
            continue

        pm = existing_by_ipdb.get(rec.ipdb_id)
        if pm:
            match_results.append(MatchResult(model=pm, record=rec))
        else:
            unmatched_records.append((rec.ipdb_id, unescape(rec.title)))

    # IPDB records must match an existing pindata MachineModel. Any record
    # with no match indicates pindata is missing the model file; abort ingest
    # and instruct the user to add it to pindata first.
    if unmatched_records:
        lines = "\n".join(
            f"  ipdb_id={ipdb_id} — {title!r}" for ipdb_id, title in unmatched_records
        )
        raise CommandError(
            f"{len(unmatched_records)} IPDB record(s) do not match any existing "
            f"MachineModel. Every IPDB machine must correspond to a pindata "
            f"model file. Add the missing models to pindata and re-run ingest:\n"
            f"{lines}"
        )

    plan.records_matched = len(match_results)

    # Collect queues for deferred processing.
    credit_queue: list[CreditQueueEntry] = []
    theme_queue: list[ThemeQueueEntry] = []
    gameplay_feature_queue: list[GameplayFeatureQueueEntry] = []
    reward_type_queue: list[RewardTypeQueueEntry] = []
    unmatched_feature_terms: list[str] = []
    unknown_mpu_strings: set[str] = set()
    ce_handles: dict[int, str] = {}  # mfr_id → handle for planned CEs

    # ── Step 3: Process each record ──────────────────────────────
    for mr in match_results:
        target: ClaimTarget = {"content_type_id": ct_mm, "object_id": mr.model.pk}

        _collect_mm_claims(mr, target, plan, mpu_to_slug, unknown_mpu_strings)

        # CE processing.
        _process_corporate_entity(
            mr,
            target,
            plan,
            ct_ce,
            resolver,
            ce_by_ipdb_id,
            ce_by_name,
            ce_slugs,
            location_lookup,
            ce_location_paths,
            ce_handles,
        )

        # Abbreviation relationship claims.
        if mr.record.common_abbreviations:
            for abbrev in mr.record.common_abbreviations.split(","):
                abbrev = unescape(abbrev.strip())
                if abbrev:
                    claim_key, value = build_relationship_claim(
                        "abbreviation", {"value": abbrev}
                    )
                    plan.assertions.append(
                        PlannedClaimAssert(
                            field_name="abbreviation",
                            claim_key=claim_key,
                            value=value,
                            **target,
                        )
                    )

        # Queue credits.
        for attr, role in CREDIT_FIELDS.items():
            raw = getattr(mr.record, attr)
            if not raw:
                continue
            for name in parse_credit_string(raw):
                credit_queue.append(CreditQueueEntry(ct_mm, mr.model.pk, name, role))

        # Queue themes.
        if mr.record.theme:
            theme_slugs = parse_ipdb_themes(
                unescape(mr.record.theme), theme_name_lookup
            )
            if theme_slugs:
                theme_queue.append(ThemeQueueEntry(target, theme_slugs))

        # Queue gameplay features + reward types.
        if mr.record.notable_features:
            raw_features = unescape(mr.record.notable_features)
            feature_pairs, unmatched = extract_ipdb_gameplay_features(
                raw_features, feature_map
            )
            unmatched_feature_terms.extend(unmatched)
            if feature_pairs:
                gameplay_feature_queue.append(
                    GameplayFeatureQueueEntry(target, feature_pairs)
                )
            reward_slugs = extract_ipdb_reward_types(raw_features, reward_map)
            if reward_slugs:
                reward_type_queue.append(RewardTypeQueueEntry(target, reward_slugs))

    # ── Step 4: Credits → Person entities + credit claims ────────
    _process_credits(
        credit_queue,
        plan,
        ct_person,
        ct_mm,
        person_lookup,
        person_slugs,
        role_slug_to_pk,
    )

    # ── Step 5: Theme entities + theme claims ────────────────────
    _process_themes(
        theme_queue,
        plan,
        ct_theme,
        theme_by_slug,
    )

    # ── Step 6: Gameplay feature + reward type claims ────────────
    _process_gameplay_features(gameplay_feature_queue, plan, feature_slug_to_pk)
    _process_reward_types(reward_type_queue, plan, reward_slug_to_pk)

    # ── Step 7: Fail on unknown MPU strings ──────────────────────
    if unknown_mpu_strings:
        lines = "\n".join(f"  {s}" for s in sorted(unknown_mpu_strings))
        raise CommandError(
            f"Unknown MPU strings not in catalog systems:\n{lines}\n"
            "Add mpu_strings entries to pindata's catalog/systems/*.md and re-export before re-ingesting."
        )

    # ── Step 8: Warnings ─────────────────────────────────────────
    if unmatched_feature_terms:
        plan.warnings.append(
            f"{len(unmatched_feature_terms)} unmatched IPDB feature term(s): "
            + ", ".join(unmatched_feature_terms[:25])
        )

    return plan


def parse_ipdb_records(ipdb_path: str) -> list[IpdbRecord]:
    """Load and parse IPDB JSON into typed records."""
    with open(ipdb_path) as f:
        data = json.load(f)

    raw_records = data["Data"]
    records: list[IpdbRecord] = []
    parse_errors = 0
    for raw in raw_records:
        if "IpdbId" not in raw:
            parse_errors += 1
            logger.warning(
                "IPDB record missing IpdbId (title=%r)",
                raw.get("Title", "<unknown>"),
            )
            continue
        try:
            records.append(IpdbRecord.from_raw(raw))
        except (KeyError, ValueError, TypeError) as e:
            parse_errors += 1
            logger.warning(
                "Unparseable IPDB record (id=%s): %s",
                raw.get("IpdbId", "?"),
                e,
            )
    if parse_errors:
        raise CommandError(
            f"{parse_errors} IPDB record(s) failed to parse — aborting to prevent partial import. "
            f"Check warnings above for details."
        )
    return records


def get_or_create_source() -> Source:
    """Get or create the IPDB source."""
    source, _ = Source.objects.update_or_create(
        slug="ipdb",
        defaults={
            "name": "IPDB",
            "source_type": "database",
            "priority": 100,
            "url": "https://www.ipdb.org",
        },
    )
    return source


def compute_fingerprint(ipdb_path: str) -> str:
    """Hash the IPDB JSON file for the IngestPlan input_fingerprint."""
    with open(ipdb_path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# ---------------------------------------------------------------------------
# MachineModel scalar claims
# ---------------------------------------------------------------------------


def _collect_mm_claims(
    mr: MatchResult,
    target: ClaimTarget,
    plan: IngestPlan,
    mpu_to_slug: dict[str, str],
    unknown_mpu_strings: set[str],
) -> None:
    """Collect scalar and extra_data claims for one MachineModel."""
    rec = mr.record

    for attr, claim_field in CLAIM_FIELDS.items():
        value = getattr(rec, attr)
        if value is None or value == "":
            continue
        if attr == "production_number":
            value = str(value)
        if isinstance(value, str):
            value = unescape(value)
        plan.assertions.append(
            PlannedClaimAssert(field_name=claim_field, value=value, **target)
        )

    # Date fields.
    if rec.date_of_manufacture:
        year, month = parse_ipdb_date(rec.date_of_manufacture)
        if year is not None:
            plan.assertions.append(
                PlannedClaimAssert(field_name="year", value=year, **target)
            )
        if month is not None:
            plan.assertions.append(
                PlannedClaimAssert(field_name="month", value=month, **target)
            )

    # Technology generation.
    technology_generation = parse_ipdb_machine_type(rec.type_short_name, rec.type)
    if technology_generation:
        plan.assertions.append(
            PlannedClaimAssert(
                field_name="technology_generation",
                value=technology_generation,
                **target,
            )
        )

    # System (MPU).
    mpu_value = rec.mpu.strip().replace("\ufffd", "") if rec.mpu else ""
    if mpu_value:
        system_slug = mpu_to_slug.get(mpu_value)
        if system_slug:
            plan.assertions.append(
                PlannedClaimAssert(field_name="system", value=system_slug, **target)
            )
        else:
            unknown_mpu_strings.add(mpu_value)

    # Image URLs.
    if rec.image_files:
        urls = [img["Url"] for img in rec.image_files if img.get("Url")]
        if urls:
            plan.assertions.append(
                PlannedClaimAssert(field_name="ipdb.image_urls", value=urls, **target)
            )


# ---------------------------------------------------------------------------
# CorporateEntity processing
# ---------------------------------------------------------------------------


def _process_corporate_entity(
    mr: MatchResult,
    target: ClaimTarget,
    plan: IngestPlan,
    ct_ce: int,
    resolver: ManufacturerResolver,
    ce_by_ipdb_id: dict[int, CorporateEntity],
    ce_by_name: dict[str, CorporateEntity],
    ce_slugs: set[str],
    location_lookup: _IPDBLocationLookup,
    ce_location_paths: dict[int, set[str]],
    ce_handles: dict[int, str],
) -> None:
    """Process IPDB manufacturer string → CE reconciliation + claims."""
    rec = mr.record
    mfr_id = rec.manufacturer_id
    raw_mfr = rec.manufacturer
    if not mfr_id or mfr_id in IPDB_SKIP_MANUFACTURER_IDS or not raw_mfr:
        return

    parsed = parse_ipdb_manufacturer_string(raw_mfr)
    company = parsed["company_name"]
    trade = parsed["trade_name"]
    location = parsed["location"]

    # Informational extra_data claims on MachineModel.
    plan.assertions.append(
        PlannedClaimAssert(
            field_name="ipdb.corporate_entity_name", value=company, **target
        )
    )
    if trade:
        plan.assertions.append(
            PlannedClaimAssert(
                field_name="ipdb.manufacturer_trade_name", value=trade, **target
            )
        )

    # Match CE: by IPDB mfr ID → by name/alias.
    ce = ce_by_ipdb_id.get(mfr_id) or ce_by_name.get(company.lower())

    if ce:
        # Skip if this manufacturer was already processed (existing or planned).
        if mfr_id in ce_handles:
            return
        ce_handles[mfr_id] = ""  # Mark as processed (empty string = existing CE)
        # Existing CE — assert claims.  Include name so the resolve layer
        # doesn't reset it to blank (CE.name is not unique, so it's not
        # auto-preserved by the resolver).  Slug is unique and auto-preserved.
        ce_target: ClaimTarget = {"content_type_id": ct_ce, "object_id": ce.pk}
        plan.assertions.append(
            PlannedClaimAssert(field_name="name", value=ce.name, **ce_target)
        )
        plan.assertions.append(
            PlannedClaimAssert(
                field_name="ipdb_manufacturer_id", value=mfr_id, **ce_target
            )
        )
        if ce.manufacturer:
            plan.assertions.append(
                PlannedClaimAssert(
                    field_name="manufacturer", value=ce.manufacturer.slug, **ce_target
                )
            )
        # Backfill IPDB ID in local lookup.
        if ce.ipdb_manufacturer_id is None:
            ce_by_ipdb_id[mfr_id] = ce

        # Location validation (existing CEs only).
        if location:
            resolved_path = get_ipdb_location(mfr_id, location, location_lookup)
            if resolved_path is None:
                raise CommandError(
                    f"IPDB mfr {mfr_id}: {location!r} does not resolve to any "
                    f"canonical Location. Add an alias to pindata or add an IPDB "
                    f"override in parsers.py."
                )
            ce_paths = ce_location_paths.get(ce.pk, set())
            if not ce_paths:
                raise CommandError(
                    f"IPDB mfr {mfr_id} ({ce.slug!r}): has location data but "
                    f"this CE has no curated location. "
                    f"Curate this CE in pindata first."
                )
            compatible = any(
                p == resolved_path
                or p.startswith(resolved_path + "/")
                or resolved_path.startswith(p + "/")
                for p in ce_paths
            )
            if not compatible:
                raise CommandError(
                    f"IPDB mfr {mfr_id}: location mismatch — "
                    f"curated={ce_paths!r}, ipdb={resolved_path!r}. "
                    f"Fix in pindata or add an IPDB override in parsers.py."
                )
    else:
        # Create new CorporateEntity.
        # Resolve manufacturer brand — must pre-exist.
        slug = (
            (trade and resolver.resolve(trade))
            or resolver.resolve_by_corporate_entity(company)
            or resolver.resolve(company)
        )
        if not slug:
            raise CommandError(
                f"IPDB mfr {mfr_id}: cannot resolve manufacturer brand for "
                f"company={company!r}, trade={trade!r}. "
                f"All manufacturers must pre-exist in the catalog."
            )
        mfr = resolver.get_by_slug(slug)
        if mfr is None:
            raise CommandError(
                f"IPDB mfr {mfr_id}: resolved manufacturer slug {slug!r} does not exist."
            )

        # Parse years_active.
        year_start = None
        year_end = None
        ya = parsed["years_active"]
        if ya:
            parts = ya.split("-")
            try:
                year_start = int(parts[0])
                if len(parts) > 1 and parts[1] != "present":
                    year_end = int(parts[1])
            except ValueError as err:
                raise CommandError(
                    f"Cannot parse years_active {ya!r} for IPDB manufacturer {company!r}"
                ) from err

        ce_slug = generate_unique_slug(company, ce_slugs)
        handle = f"ce:{mfr_id}"

        kwargs: dict[str, Any] = {
            "name": company,
            "slug": ce_slug,
            "manufacturer_id": mfr.pk,
            "ipdb_manufacturer_id": mfr_id,
            "status": "active",
        }
        if year_start is not None:
            kwargs["year_start"] = year_start
        if year_end is not None:
            kwargs["year_end"] = year_end

        plan.entities.append(
            PlannedEntityCreate(
                model_class=CorporateEntity,
                kwargs=kwargs,
                handle=handle,
            )
        )

        # Claims for all kwargs fields.
        ce_handle_target: dict[str, Any] = {"handle": handle}
        plan.assertions.append(
            PlannedClaimAssert(field_name="name", value=company, **ce_handle_target)
        )
        plan.assertions.append(
            PlannedClaimAssert(field_name="slug", value=ce_slug, **ce_handle_target)
        )
        plan.assertions.append(
            PlannedClaimAssert(
                field_name="manufacturer", value=slug, **ce_handle_target
            )
        )
        plan.assertions.append(
            PlannedClaimAssert(
                field_name="ipdb_manufacturer_id", value=mfr_id, **ce_handle_target
            )
        )
        plan.assertions.append(
            PlannedClaimAssert(field_name="status", value="active", **ce_handle_target)
        )
        if year_start is not None:
            plan.assertions.append(
                PlannedClaimAssert(
                    field_name="year_start", value=year_start, **ce_handle_target
                )
            )
        if year_end is not None:
            plan.assertions.append(
                PlannedClaimAssert(
                    field_name="year_end", value=year_end, **ce_handle_target
                )
            )

        # Track in local lookups so subsequent records with the same
        # manufacturer ID skip CE processing (claims already asserted).
        ce_handles[mfr_id] = handle
        placeholder = CorporateEntity(
            pk=None, name=company, slug=ce_slug, ipdb_manufacturer_id=mfr_id
        )
        ce_by_ipdb_id[mfr_id] = placeholder
        ce_by_name[company.lower()] = placeholder


# ---------------------------------------------------------------------------
# Credits → Person entities + credit claims
# ---------------------------------------------------------------------------


def _process_credits(
    credit_queue: list[CreditQueueEntry],
    plan: IngestPlan,
    ct_person: int,
    ct_mm: int,
    person_lookup: dict[str, Person],
    person_slugs: set[str],
    role_slug_to_pk: dict[str, int],
) -> None:
    """Deduplicate persons, plan creation for new ones, emit credit claims."""
    if not credit_queue:
        return

    # Deduplicate person names and decide which need creation.
    seen_names: set[str] = set()
    new_person_handles: dict[str, Handle] = {}  # lower_name → handle

    for entry in credit_queue:
        key = entry.name.lower()
        if key in seen_names:
            continue
        seen_names.add(key)

        if key in person_lookup:
            # Existing person — assert name claim.
            person = person_lookup[key]
            plan.assertions.append(
                PlannedClaimAssert(
                    field_name="name",
                    value=person.name,
                    content_type_id=ct_person,
                    object_id=person.pk,
                )
            )
        else:
            # New person — plan creation.
            slug = generate_unique_slug(entry.name, person_slugs)
            handle = f"person:{slug}"
            new_person_handles[key] = handle
            plan.entities.append(
                PlannedEntityCreate(
                    model_class=Person,
                    kwargs={"name": entry.name, "slug": slug, "status": "active"},
                    handle=handle,
                )
            )
            plan.assertions.append(
                PlannedClaimAssert(field_name="name", value=entry.name, handle=handle)
            )
            plan.assertions.append(
                PlannedClaimAssert(field_name="slug", value=slug, handle=handle)
            )
            plan.assertions.append(
                PlannedClaimAssert(field_name="status", value="active", handle=handle)
            )

    # Build credit relationship claims.
    for entry in credit_queue:
        key = entry.name.lower()
        role_pk = role_slug_to_pk.get(entry.role_slug.strip().lower())
        if role_pk is None:
            logger.warning(
                "Credit role slug not found in DB (skipping): %s", entry.role_slug
            )
            continue

        person_handle = new_person_handles.get(key)
        if person_handle:
            # Deferred — person is being created in this plan.
            plan.assertions.append(
                PlannedClaimAssert(
                    field_name="credit",
                    relationship_namespace="credit",
                    identity={"role": role_pk},
                    identity_refs={"person": person_handle},
                    content_type_id=entry.content_type_id,
                    object_id=entry.object_id,
                )
            )
        else:
            existing_person = person_lookup.get(key)
            if not existing_person:
                continue
            claim_key, value = build_relationship_claim(
                "credit", {"person": existing_person.pk, "role": role_pk}
            )
            plan.assertions.append(
                PlannedClaimAssert(
                    field_name="credit",
                    claim_key=claim_key,
                    value=value,
                    content_type_id=entry.content_type_id,
                    object_id=entry.object_id,
                )
            )


# ---------------------------------------------------------------------------
# Themes → Theme entities + theme claims
# ---------------------------------------------------------------------------


def _process_themes(
    theme_queue: list[ThemeQueueEntry],
    plan: IngestPlan,
    ct_theme: int,
    theme_by_slug: dict[str, Theme],
) -> None:
    """Deduplicate themes, plan creation for new ones, emit theme claims."""
    if not theme_queue:
        return

    # Discover all unique theme slugs needed.
    all_slugs: set[str] = set()
    for entry in theme_queue:
        all_slugs.update(entry.slugs)

    # Plan creation for new themes.
    new_theme_handles: dict[str, Handle] = {}  # slug → handle
    for slug in sorted(all_slugs - theme_by_slug.keys()):
        name = slug.replace("-", " ").title()
        handle = f"theme:{slug}"
        new_theme_handles[slug] = handle
        plan.entities.append(
            PlannedEntityCreate(
                model_class=Theme,
                kwargs={"name": name, "slug": slug, "status": "active"},
                handle=handle,
            )
        )
        plan.assertions.append(
            PlannedClaimAssert(field_name="name", value=name, handle=handle)
        )
        plan.assertions.append(
            PlannedClaimAssert(field_name="slug", value=slug, handle=handle)
        )
        plan.assertions.append(
            PlannedClaimAssert(field_name="status", value="active", handle=handle)
        )

    # Build theme relationship claims.
    for entry in theme_queue:
        for slug in entry.slugs:
            new_handle = new_theme_handles.get(slug)
            if new_handle:
                # Deferred — theme is being created in this plan.
                plan.assertions.append(
                    PlannedClaimAssert(
                        field_name="theme",
                        relationship_namespace="theme",
                        identity={},
                        identity_refs={"theme": new_handle},
                        **entry.target,
                    )
                )
            else:
                theme = theme_by_slug.get(slug)
                if not theme:
                    continue
                claim_key, value = build_relationship_claim(
                    "theme", {"theme": theme.pk}
                )
                plan.assertions.append(
                    PlannedClaimAssert(
                        field_name="theme",
                        claim_key=claim_key,
                        value=value,
                        **entry.target,
                    )
                )


# ---------------------------------------------------------------------------
# Gameplay features + reward types
# ---------------------------------------------------------------------------


def _process_gameplay_features(
    queue: list[GameplayFeatureQueueEntry],
    plan: IngestPlan,
    feature_slug_to_pk: dict[str, int],
) -> None:
    """Build gameplay feature relationship claims (pre-seeded, no creation)."""
    for entry in queue:
        for pair in entry.pairs:
            pk = feature_slug_to_pk.get(pair.slug)
            if pk is None:
                continue
            claim_key, value = build_relationship_claim(
                "gameplay_feature", {"gameplay_feature": pk}
            )
            if pair.repeats is not None:
                value["count"] = pair.repeats
            plan.assertions.append(
                PlannedClaimAssert(
                    field_name="gameplay_feature",
                    claim_key=claim_key,
                    value=value,
                    **entry.target,
                )
            )


def _process_reward_types(
    queue: list[RewardTypeQueueEntry],
    plan: IngestPlan,
    reward_slug_to_pk: dict[str, int],
) -> None:
    """Build reward type relationship claims (pre-seeded, no creation)."""
    for entry in queue:
        for slug in entry.slugs:
            pk = reward_slug_to_pk.get(slug)
            if pk is None:
                continue
            claim_key, value = build_relationship_claim(
                "reward_type", {"reward_type": pk}
            )
            plan.assertions.append(
                PlannedClaimAssert(
                    field_name="reward_type",
                    claim_key=claim_key,
                    value=value,
                    **entry.target,
                )
            )
