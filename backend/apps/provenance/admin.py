from django.contrib import admin

from apps.core.admin import ReadOnlyAdminMixin

from .models import (
    ChangeSet,
    Claim,
    ClaimCitationInstance,
    IngestRun,
    Source,
    SourceFieldLicense,
)


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
    list_display = ("pk", "actor", "note_truncated", "created_at")
    list_filter = ("actor",)
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
        "actor",
        "is_active",
        "created_at",
    )
    list_filter = ("actor", "is_active", "field_name")
    search_fields = ("field_name",)
    readonly_fields = ("content_type", "object_id", "changeset", "created_at")

    @admin.display(description="Value")
    def value_truncated(self, obj: Claim) -> str:
        s = str(obj.value)
        if len(s) > 80:
            return s[:80] + "..."
        return s


@admin.register(ClaimCitationInstance)
class ClaimCitationInstanceAdmin(
    ReadOnlyAdminMixin, admin.ModelAdmin[ClaimCitationInstance]
):
    """Read-only inspection view of the claim ↔ citation-instance support edges."""

    list_display = ("claim", "citation_instance")
    list_select_related = (
        "claim__actor__user",
        "claim__actor__source",
        "citation_instance__citation_source",
    )
    readonly_fields = ("claim", "citation_instance")
