"""Query-count regression for the paginated series list endpoint.

``list_series`` resolves thumbnails through the batched ``_series_thumbnails``
provider (a fixed number of queries over the page's pks) rather than per-row
work. This pins that invariant: adding rows must not add queries.
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.catalog.models import Series, Title
from apps.catalog.tests.conftest import make_machine_model


def _seed(start: int, count: int) -> None:
    for i in range(start, start + count):
        series = Series.objects.create(name=f"Series {i}", slug=f"series-{i}")
        title = Title.objects.create(
            name=f"Title {i}", slug=f"title-{i}", series=series
        )
        make_machine_model(title=title, name=f"Machine {i}", slug=f"machine-{i}")


@pytest.mark.django_db
def test_list_series_query_count_does_not_scale_with_rows(client):
    """Adding more rows to the response must not add queries."""
    _seed(start=0, count=2)
    with CaptureQueriesContext(connection) as small_ctx:
        resp = client.get("/api/series/")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 2
    small_count = len(small_ctx.captured_queries)

    _seed(start=2, count=8)

    with CaptureQueriesContext(connection) as big_ctx:
        resp = client.get("/api/series/")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 10
    big_count = len(big_ctx.captured_queries)

    assert big_count == small_count, (
        f"Query count scaled with row count: {small_count} queries at N=2, "
        f"{big_count} at N=10. Likely a refresh_from_db-per-row caused by "
        f"a Prefetch().only(...) that omits the FK back-pointer.\n"
        f"Extra queries:\n"
        + "\n".join(q["sql"] for q in big_ctx.captured_queries[small_count:])
    )
