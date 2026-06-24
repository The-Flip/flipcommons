from django.contrib import admin
from django.db.models import Model
from django.http import HttpRequest

from .models import Actor


@admin.register(Actor)
class ActorAdmin(admin.ModelAdmin[Actor]):
    """Read-only inspection view.

    Actors are created and synced only through ``ActorModel.save()`` on the
    backing record — never directly here, so add/change/delete are disabled.
    """

    list_display = ("pk", "backing_model", "priority", "resolution_status")
    list_filter = ("backing_model", "resolution_status")
    readonly_fields = ("backing_model", "priority", "resolution_status")

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
