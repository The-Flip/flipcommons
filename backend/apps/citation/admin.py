from typing import Any

from django.contrib import admin
from django.contrib.admin.options import InlineModelAdmin
from django.forms import BaseInlineFormSet, ModelForm
from django.http import HttpRequest

from .models import CitationSource, CitationSourceLink, CitationSourceRootDomain


class CitationSourceLinkInline(admin.TabularInline[CitationSourceLink, CitationSource]):
    model = CitationSourceLink
    extra = 1
    readonly_fields = ("created_by", "updated_by")


class CitationSourceRootDomainInline(
    admin.TabularInline[CitationSourceRootDomain, CitationSource]
):
    """Recognition hosts owned by a root.

    The sole edit surface for the recognition signal — there is no contributor
    endpoint for it. Shown only on root sources (see ``get_inline_instances``);
    the model's ``clean()`` rejects a domain on a child as a backstop.
    """

    model = CitationSourceRootDomain
    extra = 1
    readonly_fields = ("created_by", "updated_by")


@admin.register(CitationSource)
class CitationSourceAdmin(admin.ModelAdmin[CitationSource]):
    list_display = ("name", "source_type", "author", "year", "parent")
    list_filter = ("source_type",)
    search_fields = ("name", "author", "publisher", "isbn")
    list_select_related = ("parent",)
    readonly_fields = ("created_by", "updated_by")
    inlines = [CitationSourceLinkInline, CitationSourceRootDomainInline]

    def get_readonly_fields(
        self,
        request: HttpRequest,
        obj: CitationSource | None = None,
    ) -> tuple[str, ...]:
        if obj:  # editing existing — parent is locked
            return (*self.readonly_fields, "parent")
        return tuple(self.readonly_fields)

    def get_inline_instances(
        self,
        request: HttpRequest,
        obj: CitationSource | None = None,
    ) -> list[InlineModelAdmin[Any, CitationSource]]:
        # A recognition domain may attach only to a root, so the inline is a
        # trap on a child page — drop it there. Roots and the add form keep it.
        instances = super().get_inline_instances(request, obj)
        if obj is not None and not obj.is_root:
            instances = [
                inline
                for inline in instances
                if not isinstance(inline, CitationSourceRootDomainInline)
            ]
        return instances

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: CitationSource | None = None,
    ) -> bool:
        return False

    def save_model(
        self,
        request: HttpRequest,
        obj: CitationSource,
        form: ModelForm[CitationSource],
        change: bool,
    ) -> None:
        assert request.user.is_authenticated
        user = request.user
        if not change:
            obj.created_by = user
        obj.updated_by = user
        super().save_model(request, obj, form, change)

    def save_formset(
        self,
        request: HttpRequest,
        form: ModelForm[CitationSource],
        formset: BaseInlineFormSet[
            CitationSourceLink, CitationSource, ModelForm[CitationSourceLink]
        ]
        | BaseInlineFormSet[
            CitationSourceRootDomain,
            CitationSource,
            ModelForm[CitationSourceRootDomain],
        ],
        change: bool,
    ) -> None:
        assert request.user.is_authenticated
        user = request.user
        instances = formset.save(commit=False)
        for instance in instances:
            # Both inline models (links and recognition domains) carry editorial
            # attribution via AttributedModel.
            if not instance.pk:
                instance.created_by = user
            instance.updated_by = user
            instance.save()
        for obj in formset.deleted_objects:
            obj.delete()
        formset.save_m2m()
