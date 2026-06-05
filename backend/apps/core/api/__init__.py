"""API endpoints for the core app.

Routers are auto-discovered via the ``routers`` list convention in
``config/api.py``.
"""

from __future__ import annotations

from apps.core.api.admin_dashboard_page import admin_pages_router
from apps.core.api.entity_autocomplete import entity_autocomplete_router
from apps.core.api.link_types import link_types_router
from apps.core.api.sitemap import sitemap_router

routers = [
    ("/entity-autocomplete/", entity_autocomplete_router),
    ("/link-types/", link_types_router),
    ("/pages/admin/", admin_pages_router),
    ("/sitemap/", sitemap_router),
]
