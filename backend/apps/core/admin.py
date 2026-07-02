from django.contrib import admin
from django.db.models import Model
from django.http import HttpRequest

from .models import License


class ReadOnlyAdminMixin:
    """Disallow add / change / delete so the admin is view-only."""

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: Model | None = None
    ) -> bool:
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: Model | None = None
    ) -> bool:
        return False


@admin.register(License)
class LicenseAdmin(admin.ModelAdmin[License]):
    list_display = (
        "short_name",
        "slug",
        "spdx_id",
        "allows_display",
        "permissiveness_rank",
    )
    list_filter = ("allows_display", "requires_attribution", "restricts_commercial")
    search_fields = ("name", "short_name", "spdx_id")
    prepopulated_fields = {"slug": ("short_name",)}
    ordering = ("-permissiveness_rank",)
