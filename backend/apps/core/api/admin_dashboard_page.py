"""Admin dashboard page API.

`GET /api/pages/admin/dashboard/` — at-a-glance counts (signups, edits,
uploads) over rolling 24h / 7d / total windows, plus the most recent
event time for each. Gated by ``Activity.VIEW_ADMIN_AREA``.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.db.models import Count, Max, Model, Q, QuerySet
from django.http import HttpRequest
from django.utils import timezone
from ninja import Router, Schema
from ninja.security import django_auth

from apps.accounts.models import User
from apps.core.authz.markers import requires
from apps.core.authz.types import Activity
from apps.media.models import MediaAsset
from apps.provenance.models import ChangeSet

admin_pages_router = Router(tags=["private"], auth=django_auth)


class AdminMetricSchema(Schema):
    last_24h: int
    last_7d: int
    total: int
    # Most recent event of this kind, or None if the table is empty
    # (or has no rows matching the metric's filter).
    last_at: datetime | None


class AdminDashboardPageSchema(Schema):
    signups: AdminMetricSchema
    edits: AdminMetricSchema
    uploads: AdminMetricSchema
    generated_at: datetime


@admin_pages_router.get("dashboard/", response=AdminDashboardPageSchema)
@requires(Activity.VIEW_ADMIN_AREA)
def admin_dashboard(request: HttpRequest) -> AdminDashboardPageSchema:
    now = timezone.now()
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)

    # Pre-filter each queryset to the row population the metric describes:
    # edits count human edits (user-backed actors), excluding ingest;
    # uploads count only successful assets, not in-progress or failed attempts.
    signups = _metric(User.objects.all(), "date_joined", cutoff_24h, cutoff_7d)
    edits = _metric(
        ChangeSet.objects.filter(actor__backing_model="user"),
        "created_at",
        cutoff_24h,
        cutoff_7d,
    )
    uploads = _metric(
        MediaAsset.objects.filter(status=MediaAsset.Status.READY),
        "created_at",
        cutoff_24h,
        cutoff_7d,
    )

    return AdminDashboardPageSchema(
        signups=signups,
        edits=edits,
        uploads=uploads,
        generated_at=now,
    )


def _metric[M: Model](
    qs: QuerySet[M],
    time_field: str,
    cutoff_24h: datetime,
    cutoff_7d: datetime,
) -> AdminMetricSchema:
    """Aggregate one metric in a single SELECT.

    The caller pre-filters ``qs`` to the row population the metric
    describes; the windowed counts, total, and ``last_at`` are all
    computed against that same population.
    """
    agg = qs.aggregate(
        last_24h=Count("pk", filter=Q(**{f"{time_field}__gte": cutoff_24h})),
        last_7d=Count("pk", filter=Q(**{f"{time_field}__gte": cutoff_7d})),
        total=Count("pk"),
        last_at=Max(time_field),
    )
    return AdminMetricSchema(
        last_24h=agg["last_24h"],
        last_7d=agg["last_7d"],
        total=agg["total"],
        last_at=agg["last_at"],
    )
