from django.contrib import admin
from django.db.models import Model
from django.http import HttpRequest

from .models import (
    ChangeSet,
    CitationInstance,
    Claim,
    IngestRun,
    Source,
    SourceFieldLicense,
)


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


class SourceFieldLicenseInline(admin.TabularInline[SourceFieldLicense, Source]):
    model = SourceFieldLicense
    extra = 1


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin[Source]):
    list_display = (
        "name",
        "source_type",
        "priority",
        "is_enabled",
        "default_license",
        "url",
    )
    list_editable = ("is_enabled", "default_license")
    list_filter = ("source_type", "is_enabled")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}
    inlines = [SourceFieldLicenseInline]


@admin.register(IngestRun)
class IngestRunAdmin(ReadOnlyAdminMixin, admin.ModelAdmin[IngestRun]):
    """Read-only inspection view. IngestRun records are created by the apply layer."""

    list_display = ("pk", "patch_id", "source", "status", "started_at")
    list_filter = ("source", "status")
    readonly_fields = (
        "source",
        "status",
        "started_at",
        "finished_at",
        "input_fingerprint",
        "records_parsed",
        "records_matched",
        "records_created",
        "claims_asserted",
        "claims_retracted",
        "claims_rejected",
        "warnings",
        "errors",
    )


@admin.register(ChangeSet)
class ChangeSetAdmin(admin.ModelAdmin[ChangeSet]):
    list_display = ("pk", "user", "note_truncated", "created_at")
    list_filter = ("user",)
    readonly_fields = ("created_at",)

    @admin.display(description="Note")
    def note_truncated(self, obj: ChangeSet) -> str:
        if len(obj.note) > 80:
            return obj.note[:80] + "..."
        return obj.note


@admin.register(Claim)
class ClaimAdmin(ReadOnlyAdminMixin, admin.ModelAdmin[Claim]):
    """Read-only inspection view. Claims must not be created or edited in admin."""

    list_display = (
        "subject",
        "field_name",
        "value_truncated",
        "source",
        "is_active",
        "created_at",
    )
    list_filter = ("source", "is_active", "field_name")
    search_fields = ("field_name",)
    readonly_fields = ("content_type", "object_id", "changeset", "created_at")

    @admin.display(description="Value")
    def value_truncated(self, obj: Claim) -> str:
        s = str(obj.value)
        if len(s) > 80:
            return s[:80] + "..."
        return s


@admin.register(CitationInstance)
class CitationInstanceAdmin(ReadOnlyAdminMixin, admin.ModelAdmin[CitationInstance]):
    """Read-only inspection view. CitationInstances are immutable."""

    list_display = ("citation_source", "claim", "locator_truncated", "created_at")
    list_select_related = ("citation_source", "claim")
    readonly_fields = ("citation_source", "claim", "locator", "created_at")

    @admin.display(description="Locator")
    def locator_truncated(self, obj: CitationInstance) -> str:
        if len(obj.locator) > 60:
            return obj.locator[:60] + "..."
        return obj.locator
