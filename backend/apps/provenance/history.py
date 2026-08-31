"""Edit-history helpers for provenance changesets."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from itertools import chain

from django.contrib.contenttypes.models import ContentType

from apps.core.authz import PolicyUser, compute_row_capabilities
from apps.core.types import ClaimKey

from .attribution import actor_user_id
from .claim_citations import (
    InlineCitationLookup,
    citation_schema,
    claim_citation_schemas,
    inline_cite_pks,
    resolve_inline_citations,
)
from .claim_ranking_in_db import ranked_claims
from .display import (
    ClaimDisplayContext,
    FieldValue,
    claim_value,
    resolve_display_context,
)
from .helpers import changeset_author, citation_instances_prefetch
from .models import ChangeSet, Claim, ClaimControlledModel
from .parked_fields import HIDDEN_PARKED_FIELDS
from .schemas import (
    ChangeSetSchema,
    ClaimAttributionSchema,
    ClaimCitationSchema,
    FieldChangeSchema,
    RetractionSchema,
)

type ClaimsByKey = dict[ClaimKey, list[Claim]]
"""An entity's claims grouped by claim_key into per-slot history chains, each
ordered newest-first. A chain yields a field's prior value and the full set of
values a change is displayed against."""


def _field_change_citations(
    claim: Claim, prior: object, inline: InlineCitationLookup
) -> list[ClaimCitationSchema]:
    """Build the citation list for a field change's claim.

    The claim's own citations (see :func:`claim_citation_schemas`) come first,
    then markers only the *prior* value carries (removed by this change), so a
    client rendering a diff can label every marker on either side.
    """
    result, own_pks = claim_citation_schemas(claim, inline)
    own = set(own_pks)
    for pk in inline_cite_pks(prior):
        if pk in own:
            continue
        inst = inline.get(pk)
        if inst is not None:
            result.append(citation_schema(inst, slug=inst.slug))
    return result


def _chronological_prior_claim_value(
    claim: Claim, chain: Sequence[Claim]
) -> object | None:
    """Return the value of the claim immediately preceding ``claim`` in ``chain``.

    ``chain`` is ordered newest-first by ``(-created_at, -pk)``; the prior
    claim is the entry immediately after ``claim`` in that ordering —
    **chronological claim-log order**, regardless of actor, priority, active
    state or winning state. This is deliberately not the previously
    resolved/materialized value: edit history narrates the claim log, and a
    priority-inverted prior claim (newer but out-ranked) is still what
    ``old_value`` shows. Pinned by
    ``test_old_value_is_chronological_even_when_prior_claim_is_not_winner``.
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
    model: type[ClaimControlledModel],
    own_claims: Iterable[Claim],
    retracted: Iterable[Claim],
    history_by_key: Mapping[ClaimKey, Sequence[Claim]],
    *,
    winning_ids: set[int] | None = None,
    ctx: ClaimDisplayContext | None = None,
    inline_citations: InlineCitationLookup | None = None,
) -> tuple[list[FieldChangeSchema], list[RetractionSchema]]:
    """Build per-field changes and retractions for a changeset.

    ``model`` is the subject entity's class — all claims here belong to one
    entity, so the model is uniform; it lets display dispatch markdown fields.

    No per-row DB lookups during display building: pass a pre-built ``ctx``
    (and matching ``inline_citations``) when the caller already has them
    (e.g. a multi-changeset response that resolved references across the
    whole entity); otherwise this builds its own from the union of values
    referenced here.

    ``winning_ids`` is only meaningful for entity-wide history; omit it for
    single-changeset detail views and ``is_winning`` will be left unset.

    Parked source fields (see :mod:`.parked_fields`) are dropped from both
    lists. ``history_by_key`` needs no filtering: a parked claim's key is its
    own field name, so it can only ever chain to itself.
    """
    own = [c for c in own_claims if c.field_name not in HIDDEN_PARKED_FIELDS]
    rets = [c for c in retracted if c.field_name not in HIDDEN_PARKED_FIELDS]

    if ctx is None:
        ctx = resolve_display_context(
            FieldValue(c.field_name, c.value, model)
            for c in chain(own, rets, *history_by_key.values())
        )
    if inline_citations is None:
        inline_citations = resolve_inline_citations(
            c.value for c in chain(own, rets, *history_by_key.values())
        )

    changes: list[FieldChangeSchema] = []
    for claim in own:
        prior = _chronological_prior_claim_value(
            claim, history_by_key.get(claim.claim_key, [])
        )
        old_value = (
            claim_value(model, claim.field_name, prior, ctx)
            if prior is not None
            else None
        )
        new_value = claim_value(model, claim.field_name, claim.value, ctx)
        changes.append(
            FieldChangeSchema(
                field_name=claim.field_name,
                claim_key=claim.claim_key,
                old_value=old_value,
                new_value=new_value,
                claim_id=claim.pk,
                claim_user_id=actor_user_id(claim.actor),
                is_active=claim.is_active,
                is_winning=(
                    (claim.pk in winning_ids) if winning_ids is not None else None
                ),
                is_retracted=claim.retracted_by_changeset_id is not None,
                citations=_field_change_citations(claim, prior, inline_citations),
            )
        )

    retractions = [
        RetractionSchema(
            claim_id=c.pk,
            field_name=c.field_name,
            claim_key=c.claim_key,
            old_value=claim_value(model, c.field_name, c.value, ctx),
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
    active_claims = ranked_claims(
        Claim.objects.filter(content_type=ct, object_id=entity_pk), "claim_key"
    )

    winners: set[int] = set()
    seen_keys: set[str] = set()
    for claim in active_claims:
        if claim.claim_key not in seen_keys:
            seen_keys.add(claim.claim_key)
            winners.add(claim.pk)
    return winners


def build_edit_history(
    entity: ClaimControlledModel, user: PolicyUser
) -> list[ChangeSetSchema]:
    """Build changeset-grouped edit history with old→new diffs for an entity.

    Returns ChangeSetSchema rows newest first. Query count is bounded
    independent of changeset count: every claim the page renders is read
    once up front and grouped in memory.

    ``user`` is the caller (boundary-cast via ``policy_user``) and is
    used to populate the per-row ``capabilities`` map.
    """
    ct = ContentType.objects.get_for_model(entity)

    # Active and inactive, every author: an edit's "old value" is the field's
    # most recent prior claim whatever wrote it — an earlier user edit, an
    # ingest or a source — so narrowing this read would lose diffs.
    all_claims = list(
        Claim.objects.filter(content_type=ct, object_id=entity.pk)
        .select_related("actor__user")
        .prefetch_related(citation_instances_prefetch())
        .order_by("claim_key", "-created_at", "-pk")
    )

    # A chain is newest-first, which the query order already gives. A card
    # lists its claims by field, then pk: one changeset's claims share
    # ``created_at`` (db_default ``Now()``), so pk is all that separates them.
    history: ClaimsByKey = defaultdict(list)
    for c in all_claims:
        history[c.claim_key].append(c)

    asserted: dict[int, list[Claim]] = defaultdict(list)
    retracted: dict[int, list[Claim]] = defaultdict(list)
    for c in sorted(all_claims, key=lambda c: (c.field_name, c.pk)):
        asserted[c.changeset_id].append(c)
        if c.retracted_by_changeset_id is not None:
            retracted[c.retracted_by_changeset_id].append(c)

    # A changeset touched this entity iff it wrote or retracted one of these
    # claims, so the ids are already in hand. Filtering ChangeSet on the claim
    # join instead reads as the obvious spelling but ORs across two joins, and
    # no index covers that.
    changesets = (
        ChangeSet.objects.filter(pk__in=asserted.keys() | retracted.keys())
        .select_related("actor__user", "actor__source")
        # All ChangeSets minted in one ingest ``bulk_create`` share ``created_at``
        # (db_default ``Now()``), so for a per-entry patch run file order lives only
        # in pk — tiebreak on it to keep the timeline deterministic and ordered.
        .order_by("-created_at", "-pk")
    )

    winning_ids = _compute_winning_claim_ids(ct, entity.pk)

    # Resolve FK labels and wikilink authoring keys once across every value any
    # changeset will render: cards, retractions and chains all draw from
    # ``all_claims``, so one pass over it covers them.
    model = type(entity)
    ctx = resolve_display_context(
        FieldValue(c.field_name, c.value, model) for c in all_claims
    )
    inline_citations = resolve_inline_citations(c.value for c in all_claims)

    result: list[ChangeSetSchema] = []
    for cs in changesets:
        changes, retractions = build_changes(
            model,
            asserted.get(cs.pk, []),
            retracted.get(cs.pk, []),
            history,
            winning_ids=winning_ids,
            ctx=ctx,
            inline_citations=inline_citations,
        )
        # A changeset selected for touching this entity but left with nothing to
        # show wrote only parked fields — an ingest artifact, not an edit. Drop
        # it rather than render a card with an empty body.
        if not changes and not retractions:
            continue
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
