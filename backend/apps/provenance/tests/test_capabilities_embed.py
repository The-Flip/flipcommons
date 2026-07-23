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
from apps.provenance.test_factories import make_claim

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
