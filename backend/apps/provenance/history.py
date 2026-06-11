"""Edit-history helpers for provenance changesets."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from itertools import chain

from django.contrib.contenttypes.models import ContentType
from django.db.models import Case, F, IntegerField, Model, Prefetch, Q, Value, When

from apps.citation.models import CitationSourceLink
from apps.core.authz import PolicyUser, compute_row_capabilities

from .display import FieldValue, LabelLookup, claim_value, resolve_labels
from .helpers import changeset_author, citation_instances, citation_instances_prefetch
from .models import ChangeSet, Claim
from .schemas import (
    ChangeSetSchema,
    ClaimAttributionSchema,
    FieldChangeCitationSchema,
    FieldChangeSchema,
    RetractionSchema,
)


def _field_change_citations(claim: Claim) -> list[FieldChangeCitationSchema]:
    """Build the compact citation list for a field change's claim.

    Requires the claim to have been loaded with citation instances prefetched
    (``prefetched_citation_instances`` — see ``claims_prefetch`` and the
    edit-history / changeset-detail querysets). Uses the source's live link as
    the compact citation URL; the full set of links (incl. an ``archive``
    snapshot) is exposed by the citation-source detail surface, not here.
    """
    result: list[FieldChangeCitationSchema] = []
    for inst in citation_instances(claim):
        # Prefer the live page over its durable ``archive`` snapshot. The
        # snapshot is a backup, not the canonical link — and the default link
        # ordering sorts "archive" before "reference", so ``links[0]`` alone
        # would surface the Wayback URL. Pick on the prefetched list (no requery).
        links = list(inst.citation_source.links.all())
        live = next(
            (
                link
                for link in links
                if link.link_type != CitationSourceLink.LinkType.ARCHIVE
            ),
            links[0] if links else None,
        )
        result.append(
            FieldChangeCitationSchema(
                source_name=inst.citation_source.name,
                url=live.url if live else None,
            )
        )
    return result


def _prior_value(claim: Claim, chain: Sequence[Claim]) -> object | None:
    """Return the value of the claim immediately preceding ``claim`` in ``chain``.

    ``chain`` is ordered newest-first by ``(-created_at, -pk)``; the prior
    claim is the entry immediately after ``claim`` in that ordering.
    Returns ``None`` if ``claim`` is at the tail of the chain or absent
    from it.
    """
    for i, c in enumerate(chain):
        if c.pk == claim.pk and i + 1 < len(chain):
            # Claim.value is a JSONField (django-stubs types it Any).
            prior: object = chain[i + 1].value
            return prior
    return None


def build_changes(
    own_claims: Iterable[Claim],
    retracted: Iterable[Claim],
    history_by_key: Mapping[str, Sequence[Claim]],
    *,
    winning_ids: set[int] | None = None,
    labels: LabelLookup | None = None,
) -> tuple[list[FieldChangeSchema], list[RetractionSchema]]:
    """Build per-field changes and retractions for a changeset.

    No per-row DB lookups during display-label building: pass a pre-built ``labels``
    when the caller already has one (e.g. a multi-changeset response that
    resolved labels across the whole entity); otherwise this builds its
    own from the union of values referenced here.

    ``winning_ids`` is only meaningful for entity-wide history; omit it for
    single-changeset detail views and ``is_winning`` will be left unset.
    """
    own = list(own_claims)
    rets = list(retracted)

    if labels is None:
        labels = resolve_labels(
            FieldValue(c.field_name, c.value)
            for c in chain(own, rets, *history_by_key.values())
        )

    changes: list[FieldChangeSchema] = []
    for claim in own:
        prior = _prior_value(claim, history_by_key.get(claim.claim_key, []))
        old_value = (
            claim_value(claim.field_name, prior, labels) if prior is not None else None
        )
        new_value = claim_value(claim.field_name, claim.value, labels)
        changes.append(
            FieldChangeSchema(
                field_name=claim.field_name,
                claim_key=claim.claim_key,
                old_value=old_value,
                new_value=new_value,
                claim_id=claim.pk,
                claim_user_id=claim.user_id,
                is_active=claim.is_active,
                is_winning=(
                    (claim.pk in winning_ids) if winning_ids is not None else None
                ),
                is_retracted=claim.retracted_by_changeset_id is not None,
                citations=_field_change_citations(claim),
            )
        )

    retractions = [
        RetractionSchema(
            claim_id=c.pk,
            field_name=c.field_name,
            claim_key=c.claim_key,
            old_value=claim_value(c.field_name, c.value, labels),
        )
        for c in rets
    ]

    return changes, retractions


def _compute_winning_claim_ids(ct: ContentType, entity_pk: int) -> set[int]:
    """Return the set of claim PKs that are current winners for the entity.

    For each ``claim_key``, the winner is the active claim with the highest
    ``effective_priority``, breaking ties by most recent ``created_at``, then
    highest ``pk``.
    """
    active_claims = (
        Claim.objects.filter(
            content_type=ct,
            object_id=entity_pk,
            is_active=True,
        )
        .exclude(source__is_enabled=False)
        .annotate(
            effective_priority=Case(
                When(source__isnull=False, then=F("source__priority")),
                When(user__isnull=False, then=F("user__priority")),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
        .order_by("claim_key", "-effective_priority", "-created_at", "-pk")
    )

    winners: set[int] = set()
    seen_keys: set[str] = set()
    for claim in active_claims:
        if claim.claim_key not in seen_keys:
            seen_keys.add(claim.claim_key)
            winners.add(claim.pk)
    return winners


def build_edit_history(entity: Model, user: PolicyUser) -> list[ChangeSetSchema]:
    """Build changeset-grouped edit history with old→new diffs for an entity.

    Returns ChangeSetSchema rows newest first. Query count is bounded
    independent of changeset count: changesets+prefetches, all claims for
    the entity (for old-value lookup), winning-claim computation, and one
    query per distinct FK target model build_display_label needs to resolve.

    ``user`` is the caller (boundary-cast via ``policy_user``) and is
    used to populate the per-row ``capabilities`` map.
    """
    ct = ContentType.objects.get_for_model(entity)

    # 1. Fetch changesets that have claims OR retracted_claims for this entity.
    changesets = (
        ChangeSet.objects.filter(
            Q(claims__content_type=ct, claims__object_id=entity.pk)
            | Q(
                retracted_claims__content_type=ct,
                retracted_claims__object_id=entity.pk,
            )
        )
        .distinct()
        .select_related("user", "ingest_run__source")
        .prefetch_related(
            Prefetch(
                "claims",
                queryset=Claim.objects.filter(content_type=ct, object_id=entity.pk)
                .order_by("field_name")
                .prefetch_related(citation_instances_prefetch()),
            ),
            Prefetch(
                "retracted_claims",
                queryset=Claim.objects.filter(
                    content_type=ct, object_id=entity.pk
                ).order_by("field_name"),
            ),
        )
        .order_by("-created_at")
    )

    # 2. Fetch ALL claims for this entity (active + inactive, any author) to
    #    build a per-field history chain for old-value lookups. The "old
    #    value" for a user edit is whatever the field's most recent prior
    #    claim was — be it a previous user edit, ingest, or source.
    all_claims = list(
        Claim.objects.filter(
            content_type=ct,
            object_id=entity.pk,
        ).order_by("claim_key", "-created_at", "-pk")
    )

    # Build lookup: claim_key → list of claims ordered newest-first.
    history: dict[str, list[Claim]] = defaultdict(list)
    for c in all_claims:
        history[c.claim_key].append(c)

    # 3. Compute winning claims for is_winning.
    winning_ids = _compute_winning_claim_ids(ct, entity.pk)

    # 4. Resolve FK labels once across every value any changeset will
    #    render. ``all_claims`` is the superset (current claims, retracted
    #    claims, and history chains all draw from it), so one pass suffices.
    labels = resolve_labels(FieldValue(c.field_name, c.value) for c in all_claims)

    # 5. Build response.
    result: list[ChangeSetSchema] = []
    for cs in changesets:
        changes, retractions = build_changes(
            cs.claims.all(),
            cs.retracted_claims.all(),
            history,
            winning_ids=winning_ids,
            labels=labels,
        )
        assert cs.pk is not None
        result.append(
            ChangeSetSchema(
                id=cs.pk,
                attribution=ClaimAttributionSchema(
                    author=changeset_author(cs),
                    created_at=cs.created_at.isoformat(),
                ),
                note=cs.note,
                changes=changes,
                retractions=retractions,
                capabilities=compute_row_capabilities(
                    user, cs, ChangeSetSchema.policy_activities
                ),
            )
        )
    return result
