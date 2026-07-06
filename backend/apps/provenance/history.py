"""Edit-history helpers for provenance changesets."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from itertools import chain

from django.contrib.contenttypes.models import ContentType
from django.db.models import Prefetch, Q

from apps.citation.deep_links import deep_linked_url
from apps.citation.models import CitationInstance
from apps.core.authz import PolicyUser, compute_row_capabilities
from apps.core.types import ClaimKey
from apps.core.wikilinks import get_link_type, get_patterns

from .attribution import actor_user_id
from .claim_ranking_in_db import ranked_claims
from .display import (
    ClaimDisplayContext,
    FieldValue,
    claim_value,
    resolve_display_context,
)
from .helpers import (
    changeset_author,
    citation_instances,
    citation_instances_prefetch,
)
from .models import ChangeSet, Claim, ClaimControlledModel
from .schemas import (
    ChangeSetSchema,
    CitationLinkSchema,
    ClaimAttributionSchema,
    FieldChangeCitationSchema,
    FieldChangeSchema,
    RetractionSchema,
)

type ClaimsByKey = dict[ClaimKey, list[Claim]]
"""An entity's claims grouped by claim_key into per-slot history chains, each
ordered newest-first. A chain yields a field's prior value and the full set of
values a change is displayed against."""


class InlineCitationLookup:
    """Citation instances resolved from ``[[cite:id:N]]`` markers, keyed by pk.

    Built once per response by :func:`resolve_inline_citations`; consulted by
    :func:`_field_change_citations` so per-change citation building does no
    DB work. Same encapsulated shape as
    :class:`apps.core.markdown.field.WikilinkAuthoringLookup`.
    """

    __slots__ = ("_instances",)

    def __init__(self) -> None:
        self._instances: dict[int, CitationInstance] = {}

    def add(self, instance: CitationInstance) -> None:
        assert instance.pk is not None
        self._instances[instance.pk] = instance

    def get(self, pk: int) -> CitationInstance | None:
        return self._instances.get(pk)


def _cite_storage_pattern() -> re.Pattern[str] | None:
    """The compiled ``[[cite:id:N]]`` pattern, or None when the ``cite``
    link type isn't registered (cleared-registry tests)."""
    link_type = get_link_type("cite")
    if link_type is None:
        return None
    return get_patterns(link_type)["storage"]


def _inline_cite_pks(value: object) -> list[int]:
    """Citation-instance pks referenced by ``[[cite:id:N]]`` markers in
    *value*, in document order, deduped keeping the first occurrence."""
    if not isinstance(value, str) or not value:
        return []
    pattern = _cite_storage_pattern()
    if pattern is None:
        return []
    seen: set[int] = set()
    pks: list[int] = []
    for match in pattern.finditer(value):
        pk = int(match.group(1))
        if pk not in seen:
            seen.add(pk)
            pks.append(pk)
    return pks


def resolve_inline_citations(values: Iterable[object]) -> InlineCitationLookup:
    """Batch-load every citation instance referenced inline across *values*.

    One query (plus the links prefetch), independent of how many values are
    passed, so callers rendering many claim values stay query-bounded.
    """
    pks: set[int] = set()
    for value in values:
        pks.update(_inline_cite_pks(value))
    lookup = InlineCitationLookup()
    if not pks:
        return lookup
    instances = (
        CitationInstance.objects.filter(pk__in=pks)
        # The parent ride-along feeds deep_linked_url (scheme lookup via the
        # root's identifier_key) without a per-cite query.
        .select_related("citation_source", "citation_source__parent")
        .prefetch_related("citation_source__links")
    )
    for instance in instances:
        lookup.add(instance)
    return lookup


def _citation_schema(
    inst: CitationInstance, *, slug: str | None
) -> FieldChangeCitationSchema:
    """Serialize one citation instance for a field change."""
    source = inst.citation_source
    return FieldChangeCitationSchema(
        source_name=source.name,
        source_type=source.source_type,
        author=source.author,
        year=source.year,
        locator=inst.locator,
        slug=slug,
        links=[
            CitationLinkSchema(
                url=deep_linked_url(source, inst.locator, link.url),
                link_type=link.link_type,
                display_name=link.display_name,
            )
            for link in source.links.all()
        ],
    )


def _field_change_citations(
    claim: Claim, prior: object, inline: InlineCitationLookup
) -> list[FieldChangeCitationSchema]:
    """Build the citation list for a field change's claim.

    Attached (join-row) evidence comes first and requires the claim to have
    been loaded with citation instances prefetched
    (``prefetched_citation_instances`` — see ``claims_prefetch`` and the
    edit-history / changeset-detail querysets). Inline citations follow:
    ``[[cite:id:N]]`` markers from the claim's own value in document order,
    then markers only the *prior* value carries (removed by this change), so
    a client rendering a diff can label every marker on either side. Markers
    whose instance row is gone are skipped, matching the editor's
    broken-link degrade.
    """
    result = [_citation_schema(inst, slug=None) for inst in citation_instances(claim)]
    pks = _inline_cite_pks(claim.value)
    own = set(pks)
    pks += [pk for pk in _inline_cite_pks(prior) if pk not in own]
    for pk in pks:
        inst = inline.get(pk)
        if inst is not None:
            result.append(_citation_schema(inst, slug=inst.slug))
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
    """
    own = list(own_claims)
    rets = list(retracted)

    if ctx is None:
        ctx = resolve_display_context(
            FieldValue(c.field_name, c.value)
            for c in chain(own, rets, *history_by_key.values())
        )
    if inline_citations is None:
        inline_citations = resolve_inline_citations(
            c.value for c in chain(own, rets, *history_by_key.values())
        )

    changes: list[FieldChangeSchema] = []
    for claim in own:
        prior = _prior_value(claim, history_by_key.get(claim.claim_key, []))
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
    independent of changeset count: changesets+prefetches, all claims for
    the entity (for old-value lookup), winning-claim computation, one query
    per distinct FK target model display needs to resolve, one per
    public-id link type for markdown wikilink rendering, and one (plus a
    links prefetch) for inline citation instances.

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
        .select_related("actor__user", "actor__source")
        .prefetch_related(
            Prefetch(
                "claims",
                queryset=Claim.objects.filter(content_type=ct, object_id=entity.pk)
                .select_related("actor__user")
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
        # All ChangeSets minted in one ingest ``bulk_create`` share ``created_at``
        # (db_default ``Now()``), so for a per-entry patch run file order lives only
        # in pk — tiebreak on it to keep the timeline deterministic and ordered.
        .order_by("-created_at", "-pk")
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
    history: ClaimsByKey = defaultdict(list)
    for c in all_claims:
        history[c.claim_key].append(c)

    # 3. Compute winning claims for is_winning.
    winning_ids = _compute_winning_claim_ids(ct, entity.pk)

    # 4. Resolve FK labels and wikilink authoring keys once across every value
    #    any changeset will render. ``all_claims`` is the superset (current
    #    claims, retracted claims, and history chains all draw from it), so one
    #    pass suffices.
    ctx = resolve_display_context(FieldValue(c.field_name, c.value) for c in all_claims)
    inline_citations = resolve_inline_citations(c.value for c in all_claims)
    model = type(entity)

    # 5. Build response.
    result: list[ChangeSetSchema] = []
    for cs in changesets:
        changes, retractions = build_changes(
            model,
            cs.claims.all(),
            cs.retracted_claims.all(),
            history,
            winning_ids=winning_ids,
            ctx=ctx,
            inline_citations=inline_citations,
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
