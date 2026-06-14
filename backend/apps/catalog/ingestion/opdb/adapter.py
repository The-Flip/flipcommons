"""OPDB source adapter: parse, reconcile, collect claims → IngestPlan.

Converts OPDB JSON data into an IngestPlan for the apply layer.
No database writes — all mutations happen in apply_plan().

The adapter handles:
- Matching OPDB records to existing MachineModels (by opdb_id, then ipdb_id);
  unmatched records abort ingest (pindata is the authoritative superset)
- Collecting scalar and relationship claims as PlannedClaimAssert
- Classifying OPDB features into gameplay features, reward types, tags, cabinets
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import CommandError

from apps.catalog.claims import build_relationship_claim
from apps.catalog.ingestion.opdb.records import OpdbRecord
from apps.catalog.ingestion.parsers import (
    map_opdb_display,
    map_opdb_type,
    parse_opdb_date,
)
from apps.catalog.ingestion.plan import (
    IngestPlan,
    PlannedClaimAssert,
)
from apps.catalog.ingestion.vocabulary import (
    build_cabinet_map,
    build_feature_slug_map,
    build_reward_type_map,
    build_tag_map,
)
from apps.catalog.models import (
    GameplayFeature,
    MachineModel,
    Manufacturer,
    RewardType,
    Tag,
)
from apps.catalog.resolve import (
    resolve_all_gameplay_features,
    resolve_all_model_abbreviations,
    resolve_all_reward_types,
    resolve_all_tags,
)
from apps.core.types import ClaimTarget
from apps.provenance.models import Source

logger = logging.getLogger(__name__)

# OPDB feature terms that are variant labels, not vocabulary terms.
_KNOWN_OPDB_VARIANT_LABELS: frozenset[str] = frozenset(
    {
        "Limited Edition",
        "LE",
        "Special Edition",
        "SE",
        "Premium",
        "Pro",
        "Home Edition",
        "Home ROM",
        "Shaker Motor",
        "PinSound",
        "Topper",
        "Conversion kit",
        "Converted game",
        "LED",
        "LED Upgrade",
        "Colorization",
        "Color DMD",
    }
)


# ---------------------------------------------------------------------------
# Reconciliation result
# ---------------------------------------------------------------------------


@dataclass
class MatchResult:
    """An OPDB record paired with the existing MachineModel it reconciled to."""

    model: MachineModel
    record: OpdbRecord


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_opdb_plan(
    records: list[OpdbRecord],
    source: Source,
    input_fingerprint: str,
) -> IngestPlan:
    """Build an IngestPlan from parsed OPDB records.

    Adapter-level warnings (unmatched feature terms, unrepresented
    manufacturers) are collected in ``plan.warnings``.
    """
    ct_id = ContentType.objects.get_for_model(MachineModel).pk

    # Build vocabulary maps for feature classification.
    feature_map = build_feature_slug_map()
    reward_map = build_reward_type_map()
    tag_map = build_tag_map()
    cabinet_map = build_cabinet_map()

    # Partition records.
    machines = [r for r in records if r.is_machine and r.physical_machine != 0]
    aliases = [r for r in records if r.is_alias]

    # Reconcile against existing entities. OPDB records must match an existing
    # pindata MachineModel; any record with no match aborts ingest (pindata is
    # the authoritative superset — add the missing model there and re-run).
    by_opdb_id, by_ipdb_id = _prefetch_lookups()
    match_results, unmatched = _reconcile_machines(machines, by_opdb_id, by_ipdb_id)
    alias_results, alias_warnings, alias_unmatched = _reconcile_aliases(
        aliases, by_opdb_id, by_ipdb_id
    )
    match_results.extend(alias_results)
    unmatched.extend(alias_unmatched)
    if unmatched:
        lines = "\n".join(f"  {r.opdb_id} — {r.name!r}" for r in unmatched)
        raise CommandError(
            f"{len(unmatched)} OPDB record(s) do not match any existing "
            f"MachineModel. Every OPDB machine must correspond to a pindata "
            f"model file. Add the missing models to pindata and re-run ingest:\n"
            f"{lines}"
        )

    # Build the plan.
    plan = IngestPlan(
        source=source,
        input_fingerprint=input_fingerprint,
        records_parsed=len(records),
        records_matched=len(match_results),
    )

    # Register relationship resolve hooks.
    plan.resolve_hooks[ct_id] = [
        resolve_all_gameplay_features,
        resolve_all_model_abbreviations,
        resolve_all_reward_types,
        resolve_all_tags,
    ]

    # Validate vocabulary slugs and build slug→PK lookups for claim building.
    feature_slug_to_pk = dict(GameplayFeature.objects.values_list("slug", "pk"))
    reward_slug_to_pk = dict(RewardType.objects.values_list("slug", "pk"))
    tag_slug_to_pk = dict(Tag.objects.values_list("slug", "pk"))

    unmatched_opdb_terms: list[str] = []

    for mr in match_results:
        target_kwargs: ClaimTarget = {
            "content_type_id": ct_id,
            "object_id": mr.model.pk,
        }
        _collect_claims(mr.record, plan.assertions, **target_kwargs)

        # Classify features into vocabulary claims.
        if mr.record.features:
            (
                gameplay_slugs,
                reward_slugs,
                tag_slugs,
                cabinet_slug,
                unmatched_feature_terms,
            ) = _classify_opdb_features(
                mr.record.features,
                feature_map,
                reward_map,
                tag_map,
                cabinet_map,
            )
            unmatched_opdb_terms.extend(unmatched_feature_terms)

            for slug in gameplay_slugs:
                pk = feature_slug_to_pk.get(slug)
                if pk is None:
                    continue
                claim_key, value = build_relationship_claim(
                    "gameplay_feature",
                    {"gameplay_feature": pk},
                )
                plan.assertions.append(
                    PlannedClaimAssert(
                        field_name="gameplay_feature",
                        claim_key=claim_key,
                        value=value,
                        **target_kwargs,
                    )
                )

            for slug in reward_slugs:
                pk = reward_slug_to_pk.get(slug)
                if pk is None:
                    continue
                claim_key, value = build_relationship_claim(
                    "reward_type",
                    {"reward_type": pk},
                )
                plan.assertions.append(
                    PlannedClaimAssert(
                        field_name="reward_type",
                        claim_key=claim_key,
                        value=value,
                        **target_kwargs,
                    )
                )

            for slug in tag_slugs:
                pk = tag_slug_to_pk.get(slug)
                if pk is None:
                    continue
                claim_key, value = build_relationship_claim(
                    "tag",
                    {"tag": pk},
                )
                plan.assertions.append(
                    PlannedClaimAssert(
                        field_name="tag",
                        claim_key=claim_key,
                        value=value,
                        **target_kwargs,
                    )
                )

            if cabinet_slug:
                plan.assertions.append(
                    PlannedClaimAssert(
                        field_name="cabinet",
                        value=cabinet_slug,
                        **target_kwargs,
                    )
                )

    # Collect warnings on the plan.
    plan.warnings.extend(alias_warnings)
    if unmatched_opdb_terms:
        plan.warnings.append(
            f"{len(unmatched_opdb_terms)} unmatched OPDB feature term(s): "
            + ", ".join(unmatched_opdb_terms[:25])
        )
    plan.warnings.extend(_manufacturer_diagnostics(machines))

    return plan


def compute_fingerprint(opdb_path: str) -> str:
    """Hash the OPDB JSON file for the IngestPlan input_fingerprint."""
    with open(opdb_path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def _manufacturer_diagnostics(machines: list[OpdbRecord]) -> list[str]:
    """Return warnings for OPDB manufacturers not represented in the catalog."""
    catalog_opdb_mfr_ids = set(
        Manufacturer.objects.filter(
            opdb_manufacturer_id__isnull=False,
        ).values_list("opdb_manufacturer_id", flat=True)
    )
    opdb_mfr_by_id: dict[int, str] = {}
    for rec in machines:
        if (
            rec.manufacturer_id is not None
            and rec.manufacturer_id not in opdb_mfr_by_id
        ):
            opdb_mfr_by_id[rec.manufacturer_id] = rec.manufacturer_name
    missing_ids = set(opdb_mfr_by_id) - catalog_opdb_mfr_ids
    if not missing_ids:
        return []
    names = [f"{opdb_mfr_by_id[mid]} (opdb_id={mid})" for mid in sorted(missing_ids)]
    return [
        f"{len(missing_ids)} OPDB manufacturer(s) not in catalog: " + ", ".join(names)
    ]


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def _prefetch_lookups() -> tuple[dict[str, MachineModel], dict[int, MachineModel]]:
    """Pre-fetch all MachineModels into lookup dicts."""
    by_opdb_id: dict[str, MachineModel] = {}
    for pm in MachineModel.objects.filter(opdb_id__isnull=False):
        if pm.opdb_id is not None:
            by_opdb_id[pm.opdb_id] = pm

    by_ipdb_id: dict[int, MachineModel] = {}
    for pm in MachineModel.objects.filter(ipdb_id__isnull=False):
        if pm.ipdb_id is not None:
            by_ipdb_id[pm.ipdb_id] = pm
    return by_opdb_id, by_ipdb_id


def _reconcile_machines(
    machines: list[OpdbRecord],
    by_opdb_id: dict[str, MachineModel],
    by_ipdb_id: dict[int, MachineModel],
) -> tuple[list[MatchResult], list[OpdbRecord]]:
    """Match machine records to existing MachineModels.

    Returns (matched results, unmatched records). Unmatched records drive
    the ingest-aborting CommandError upstream.
    """
    results: list[MatchResult] = []
    unmatched: list[OpdbRecord] = []

    for rec in machines:
        pm = by_opdb_id.get(rec.opdb_id)
        if not pm and rec.ipdb_id:
            pm = by_ipdb_id.get(rec.ipdb_id)

        if pm:
            # Cross-reference backfill: if matched by ipdb_id, register in
            # the opdb_id lookup so aliases can find their parent later.
            if rec.opdb_id and rec.opdb_id not in by_opdb_id:
                by_opdb_id[rec.opdb_id] = pm
            results.append(MatchResult(model=pm, record=rec))
        else:
            unmatched.append(rec)

    return results, unmatched


def _reconcile_aliases(
    aliases: list[OpdbRecord],
    by_opdb_id: dict[str, MachineModel],
    by_ipdb_id: dict[int, MachineModel],
) -> tuple[list[MatchResult], list[str], list[OpdbRecord]]:
    """Match alias records to existing MachineModels.

    Returns (matched results, warnings, unmatched records). Orphan aliases
    (parent not found) produce a warning and are silently skipped; aliases
    whose opdb_id has no matching MM but whose parent *is* found are
    reported as unmatched and abort ingest upstream.
    """
    results: list[MatchResult] = []
    warnings: list[str] = []
    unmatched: list[OpdbRecord] = []

    for rec in aliases:
        pm = by_opdb_id.get(rec.opdb_id)
        if not pm and rec.ipdb_id:
            pm = by_ipdb_id.get(rec.ipdb_id)

        if pm:
            results.append(MatchResult(model=pm, record=rec))
            continue

        if by_opdb_id.get(rec.parent_opdb_id) is None:
            warnings.append(
                f"Alias {rec.opdb_id} ({rec.name}): "
                f"parent {rec.parent_opdb_id} not found, skipping"
            )
            continue

        unmatched.append(rec)

    return results, warnings, unmatched


# ---------------------------------------------------------------------------
# Claim collection
# ---------------------------------------------------------------------------


def _collect_claims(
    rec: OpdbRecord,
    assertions: list[PlannedClaimAssert],
    *,
    content_type_id: int,
    object_id: int,
) -> None:
    """Collect scalar claims for one record into the assertions list."""

    def _add(field_name: str, value: object) -> None:
        assertions.append(
            PlannedClaimAssert(
                field_name=field_name,
                value=value,
                content_type_id=content_type_id,
                object_id=object_id,
            )
        )

    if rec.name:
        _add("name", rec.name)
    if rec.opdb_id:
        _add("opdb_id", rec.opdb_id)

    # Date.
    if rec.manufacture_date:
        year, month = parse_opdb_date(rec.manufacture_date)
        if year is not None:
            _add("year", year)
        if month is not None:
            _add("month", month)

    # Player count.
    if rec.player_count is not None:
        _add("player_count", rec.player_count)

    # Technology generation (slug-based, resolved to FK).
    technology_generation = map_opdb_type(rec.type)
    if technology_generation:
        _add("technology_generation", technology_generation)

    # Display type (slug-based, resolved to FK).
    display_type = map_opdb_display(rec.display)
    if display_type:
        _add("display_type", display_type)

    # Raw features for reference.
    if rec.features:
        _add("opdb.features", rec.features)

    for attr, claim_field in (
        ("keywords", "opdb.keywords"),
        ("description", "opdb.description"),
        ("common_name", "opdb.common_name"),
        ("images", "opdb.images"),
    ):
        value = getattr(rec, attr)
        if value:
            _add(claim_field, value)

    # Shortname → abbreviation relationship claim.
    if rec.shortname:
        claim_key, abbr_value = build_relationship_claim(
            "abbreviation",
            {"value": rec.shortname},
        )
        assertions.append(
            PlannedClaimAssert(
                field_name="abbreviation",
                claim_key=claim_key,
                value=abbr_value,
                content_type_id=content_type_id,
                object_id=object_id,
            )
        )


# ---------------------------------------------------------------------------
# Feature classification (unchanged logic, moved from management command)
# ---------------------------------------------------------------------------


def _classify_opdb_features(
    features: list[str],
    feature_map: dict[str, str],
    reward_map: dict[str, str],
    tag_map: dict[str, str],
    cabinet_map: dict[str, str],
) -> tuple[list[str], list[str], list[str], str | None, list[str]]:
    """Classify OPDB features array terms against vocabulary maps.

    Priority: reward types first, then gameplay features, then tags, then cabinets.

    Returns (gameplay_slugs, reward_slugs, tag_slugs, cabinet_slug, unmatched).
    """
    gameplay_slugs: list[str] = []
    reward_slugs: list[str] = []
    tag_slugs: list[str] = []
    cabinet_slug: str | None = None
    unmatched: list[str] = []

    seen_gameplay: set[str] = set()
    seen_reward: set[str] = set()
    seen_tag: set[str] = set()

    for term in features:
        lower = term.lower()

        if lower in reward_map:
            slug = reward_map[lower]
            if slug not in seen_reward:
                seen_reward.add(slug)
                reward_slugs.append(slug)
            continue

        if lower in feature_map:
            slug = feature_map[lower]
            if slug not in seen_gameplay:
                seen_gameplay.add(slug)
                gameplay_slugs.append(slug)
            continue

        if lower in tag_map:
            slug = tag_map[lower]
            if slug not in seen_tag:
                seen_tag.add(slug)
                tag_slugs.append(slug)
            continue

        if lower in cabinet_map:
            cabinet_slug = cabinet_map[lower]
            continue

        if term in _KNOWN_OPDB_VARIANT_LABELS:
            continue

        unmatched.append(term)

    return gameplay_slugs, reward_slugs, tag_slugs, cabinet_slug, unmatched


# ---------------------------------------------------------------------------
# Parsing helper (used by the management command)
# ---------------------------------------------------------------------------


def parse_opdb_records(raw_data: list[dict[str, Any]]) -> list[OpdbRecord]:
    """Parse raw JSON dicts into OpdbRecords, raising on any parse errors."""
    records: list[OpdbRecord] = []
    parse_errors = 0
    for raw in raw_data:
        if "opdb_id" not in raw:
            parse_errors += 1
            logger.warning(
                "OPDB record missing opdb_id (name=%r)",
                raw.get("name", "<unknown>"),
            )
            continue
        try:
            records.append(OpdbRecord.from_raw(raw))
        except (KeyError, ValueError, TypeError) as e:
            parse_errors += 1
            logger.warning(
                "Unparseable OPDB record (id=%s): %s",
                raw.get("opdb_id", "?"),
                e,
            )
    if parse_errors:
        raise ValueError(
            f"{parse_errors} OPDB record(s) failed to parse — aborting to "
            f"prevent partial import. Check warnings above for details."
        )
    return records


def get_or_create_source() -> Source:
    """Get or create the OPDB source."""
    source, _ = Source.objects.update_or_create(
        slug="opdb",
        defaults={
            "name": "OPDB",
            "source_type": "database",
            "priority": 200,
            "url": "https://opdb.org",
        },
    )
    return source
