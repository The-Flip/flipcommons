"""Meta-test: per-row ``capabilities`` embedding doesn't scale queries with N.

For every list endpoint that embeds a target-aware ``capabilities`` map on
each ChangeSet row, the query count at N=20 rows must equal the query count
at N=2 rows. Narrow scope by design — this catches embed-loop N+1 (e.g. an
accidental ``cs.user`` lookup inside the per-row loop) and nothing else.

The policy's ``ChangeSetPolicyView`` reads only ``id`` and ``actor_id``, which
live on the row itself, so no prefetch helper is needed today. When a future
target Protocol grows a relation, this test fails first.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.test_factories import make_user
from apps.catalog.tests.conftest import make_machine_model
from apps.citation.test_factories import make_citation_source
from apps.provenance.test_factories import make_citation_instance, make_claim

pytestmark = pytest.mark.django_db


def _seed_changesets(client, user, pm, n: int) -> None:
    """Create ``n`` edits on ``pm`` as ``user``, each producing one changeset."""
    client.force_login(user)
    for i in range(n):
        # Cycle years so each PATCH creates a new claim row (and changeset).
        year = 1990 + i
        resp = client.patch(
            f"/api/models/{pm.slug}/claims/",
            data=f'{{"fields": {{"year": {year}}}}}',
            content_type="application/json",
        )
        # Assert success — otherwise the N=2 vs N=20 query-count diff
        # could compare two empty reads and pass vacuously.
        assert resp.status_code == 200, (
            f"seed PATCH failed with {resp.status_code}: {resp.content!r}"
        )


def _q(fn: Callable[[], object]) -> int:
    with CaptureQueriesContext(connection) as ctx:
        fn()
    return len(ctx.captured_queries)


def test_edit_history_capabilities_does_not_scale_queries(client, bootstrap_source):
    """GET /api/pages/edit-history/... query count must not grow with N rows."""
    user = make_user()
    pm = make_machine_model(name="MM", slug="mm-x", year=1997)
    make_claim(pm, "name", "MM", ingest_source=bootstrap_source)

    _seed_changesets(client, user, pm, 2)
    # Fetch anonymously so we don't tangle with session refresh side-effects.
    client.logout()
    url = f"/api/pages/edit-history/model/{pm.slug}/"
    base = _q(lambda: client.get(url))

    _seed_changesets(client, user, pm, 18)
    client.logout()
    scaled = _q(lambda: client.get(url))

    assert scaled == base, (
        f"edit-history embed scales queries with N: {base} -> {scaled}. "
        f"A per-row ``capabilities`` lookup is hitting the DB; either a "
        f"target Protocol read traverses a relation that isn't prefetched, "
        f"or the serializer is doing a DB read inside the loop."
    )


def test_global_changes_feed_capabilities_does_not_scale_queries(
    client, bootstrap_source
):
    """GET /api/pages/changesets/ query count must not grow with N rows."""
    user = make_user()
    pm = make_machine_model(name="MM2", slug="mm-y", year=1997)
    make_claim(pm, "name", "MM2", ingest_source=bootstrap_source)

    _seed_changesets(client, user, pm, 2)
    client.logout()
    base = _q(lambda: client.get("/api/pages/changesets/"))

    _seed_changesets(client, user, pm, 18)
    client.logout()
    scaled = _q(lambda: client.get("/api/pages/changesets/"))

    assert scaled == base, (
        f"global changes-feed embed scales queries with N: {base} -> {scaled}."
    )


def _seed_cited_claims(pm, citation_source, start: int, n: int) -> None:
    """Add ``n`` claims to ``pm``, each by its own actor and each carrying
    an inline ``[[cite:id:N]]`` marker in its value.

    Scales the axis that can actually regress. The attached-citation count
    cannot: ``citation_instances()`` raises when its prefetch is missing
    rather than falling back to a per-row query, so dropping that prefetch
    fails loudly instead of quietly N+1-ing. What *can* regress is the
    per-claim batching in ``build_sources`` — ``resolve_display_context`` and
    ``resolve_inline_citations`` each issue one query for the whole list, and
    both would go per-claim if moved inside the loop. Both scale with claim
    count, and inline markers are what gives the second one anything to do.
    """
    for i in range(start, start + n):
        instance = make_citation_instance(citation_source=citation_source)
        # Namespaced names park in extra_data, so each claim is its own field
        # without needing 20 real columns.
        make_claim(
            pm,
            f"probe.note_{i}",
            f"Copy [[cite:id:{instance.pk}]] {i}",
            user=make_user(),
        )


def test_sources_page_does_not_scale_queries_with_claim_count(client, bootstrap_source):
    """GET /api/pages/sources/... query count must not grow with N claims.

    Distinct actors and distinct fields per claim, so a regression in either
    the display-context batch or the inline-citation batch shows up here.
    """
    pm = make_machine_model(name="MM3", slug="mm-z")
    citation_source = make_citation_source(name="Flyer", source_type="web")

    _seed_cited_claims(pm, citation_source, 0, 2)
    base = _q(lambda: client.get("/api/pages/sources/model/mm-z/"))

    _seed_cited_claims(pm, citation_source, 2, 18)
    scaled = _q(lambda: client.get("/api/pages/sources/model/mm-z/"))

    # Guard against a vacuous pass: the endpoint must actually be serving the
    # claims we seeded, not 404ing or returning an empty list.
    resp = client.get("/api/pages/sources/model/mm-z/")
    assert resp.status_code == 200
    body = resp.json()["sources"]
    probes = [c for c in body if c["field_name"].startswith("probe.")]
    assert len(probes) == 20
    assert sum(len(claim["citations"]) for claim in probes) == 20

    assert scaled == base, (
        f"sources page scales queries with claim count: {base} -> {scaled}."
    )


def test_user_profile_recent_edits_capabilities_does_not_scale_queries(
    client, bootstrap_source
):
    """GET /api/pages/user/{username}/ recent_edits embed must not scale queries."""
    user = make_user()
    pm = make_machine_model(name="MM4", slug="mm-w", year=1997)
    make_claim(pm, "name", "MM4", ingest_source=bootstrap_source)

    _seed_changesets(client, user, pm, 2)
    client.logout()
    base = _q(lambda: client.get(f"/api/pages/user/{user.username}/"))

    _seed_changesets(client, user, pm, 18)
    client.logout()
    scaled = _q(lambda: client.get(f"/api/pages/user/{user.username}/"))

    assert scaled == base, (
        f"user-profile recent_edits embed scales queries with N: {base} -> {scaled}."
    )
