"""Tests for citation admin configuration."""

from typing import Any

import pytest
from django.contrib import admin
from django.forms import inlineformset_factory
from django.test import RequestFactory

from apps.citation.admin import (
    CitationSourceAdmin,
    CitationSourceRootDomainInline,
)
from apps.citation.models import (
    CitationSource,
    CitationSourceLink,
    CitationSourceRootDomain,
)

LinkFormSetCreate: Any = inlineformset_factory(
    CitationSource,
    CitationSourceLink,
    fields=("link_type", "url", "label"),
    extra=1,
    can_delete=True,
)
LinkFormSetUpdate: Any = inlineformset_factory(
    CitationSource,
    CitationSourceLink,
    fields=("link_type", "url", "label"),
    extra=0,
    can_delete=True,
)
RootDomainFormSetCreate: Any = inlineformset_factory(
    CitationSource,
    CitationSourceRootDomain,
    fields=("host",),
    extra=1,
    can_delete=True,
)
RootDomainFormSetUpdate: Any = inlineformset_factory(
    CitationSource,
    CitationSourceRootDomain,
    fields=("host",),
    extra=0,
    can_delete=True,
)


@pytest.fixture
def request_factory():
    return RequestFactory()


@pytest.fixture
def admin_instance():
    return CitationSourceAdmin(CitationSource, admin.site)


class TestAdminRegistration:
    def test_citation_source_registered(self):
        assert CitationSource in admin.site._registry

    def test_citation_source_link_not_standalone(self):
        assert CitationSourceLink not in admin.site._registry


class TestCitationSourceAdminPermissions:
    def test_delete_permission_denied(self, admin_instance, request_factory, superuser):
        request = request_factory.get("/")
        request.user = superuser
        assert admin_instance.has_delete_permission(request) is False

    def test_delete_permission_denied_with_obj(
        self, admin_instance, request_factory, superuser, citation_source
    ):
        request = request_factory.get("/")
        request.user = superuser
        assert admin_instance.has_delete_permission(request, citation_source) is False


class TestCitationSourceAdminReadonlyFields:
    def test_parent_editable_on_create(
        self, admin_instance, request_factory, superuser
    ):
        request = request_factory.get("/")
        request.user = superuser
        readonly = admin_instance.get_readonly_fields(request, obj=None)
        assert "parent" not in readonly

    def test_parent_readonly_on_change(
        self, admin_instance, request_factory, superuser, citation_source
    ):
        request = request_factory.get("/")
        request.user = superuser
        readonly = admin_instance.get_readonly_fields(request, obj=citation_source)
        assert "parent" in readonly

    def test_created_by_always_readonly(
        self, admin_instance, request_factory, superuser
    ):
        request = request_factory.get("/")
        request.user = superuser
        # Readonly on create
        readonly_create = admin_instance.get_readonly_fields(request, obj=None)
        assert "created_by" in readonly_create
        assert "updated_by" in readonly_create


class TestCitationSourceAdminAttribution:
    def test_created_by_set_on_create(self, admin_instance, request_factory, superuser):
        request = request_factory.post("/")
        request.user = superuser
        obj = CitationSource(name="Test", source_type="book")
        admin_instance.save_model(request, obj, form=None, change=False)
        assert obj.created_by == superuser.actor
        assert obj.updated_by == superuser.actor

    def test_updated_by_set_on_change(
        self, admin_instance, request_factory, superuser, citation_source
    ):
        request = request_factory.post("/")
        request.user = superuser
        admin_instance.save_model(request, citation_source, form=None, change=True)
        assert citation_source.updated_by == superuser.actor
        # created_by should not be overwritten on change
        assert citation_source.created_by is None


class TestCitationSourceLinkInlineAttribution:
    """Test that save_formset auto-populates created_by/updated_by on inline links."""

    def test_created_by_set_on_new_link(
        self, admin_instance, request_factory, superuser, citation_source
    ):
        data = {
            "links-TOTAL_FORMS": "1",
            "links-INITIAL_FORMS": "0",
            "links-0-link_type": "homepage",
            "links-0-url": "https://example.com",
            "links-0-label": "Example",
        }
        formset = LinkFormSetCreate(data, instance=citation_source, prefix="links")
        assert formset.is_valid(), formset.errors

        request = request_factory.post("/")
        request.user = superuser
        admin_instance.save_formset(request, form=None, formset=formset, change=True)

        link = CitationSourceLink.objects.get(citation_source=citation_source)
        assert link.created_by == superuser.actor
        assert link.updated_by == superuser.actor

    def test_updated_by_set_on_existing_link(
        self, admin_instance, request_factory, superuser, citation_source
    ):
        link = CitationSourceLink.objects.create(
            citation_source=citation_source,
            link_type="homepage",
            url="https://example.com",
            label="Old Label",
        )
        assert link.created_by is None

        data = {
            "links-TOTAL_FORMS": "1",
            "links-INITIAL_FORMS": "1",
            "links-0-id": str(link.pk),
            "links-0-link_type": "homepage",
            "links-0-url": "https://example.com",
            "links-0-label": "New Label",
        }
        formset = LinkFormSetUpdate(data, instance=citation_source, prefix="links")
        assert formset.is_valid(), formset.errors

        request = request_factory.post("/")
        request.user = superuser
        admin_instance.save_formset(request, form=None, formset=formset, change=True)

        link.refresh_from_db()
        assert link.updated_by == superuser.actor
        # created_by should NOT be set on update of existing record
        assert link.created_by is None


class TestCitationSourceRootDomainInline:
    """The recognition-host inline: roots only, saved through save_formset."""

    def test_domain_created_through_admin_form(
        self, admin_instance, request_factory, superuser, citation_source
    ):
        # A non-normalized host proves clean() fires through the formset path —
        # the integration recognition depends on — not just on the bare model.
        data = {
            "root_domains-TOTAL_FORMS": "1",
            "root_domains-INITIAL_FORMS": "0",
            "root_domains-0-host": "WWW.Example.com",
        }
        formset = RootDomainFormSetCreate(
            data, instance=citation_source, prefix="root_domains"
        )
        assert formset.is_valid(), formset.errors

        request = request_factory.post("/")
        request.user = superuser
        admin_instance.save_formset(request, form=None, formset=formset, change=True)

        domain = CitationSourceRootDomain.objects.get(source=citation_source)
        assert domain.host == "example.com"
        # The inline stamps editorial attribution like the link inline does.
        assert domain.created_by == superuser.actor
        assert domain.updated_by == superuser.actor

    def test_domain_removed_through_admin_form(
        self, admin_instance, request_factory, superuser, citation_source
    ):
        # Removing an alias is a first-class use of this inline; exercise the
        # formset.deleted_objects path end to end.
        domain = CitationSourceRootDomain.objects.create(
            source=citation_source, host="example.com"
        )
        data = {
            "root_domains-TOTAL_FORMS": "1",
            "root_domains-INITIAL_FORMS": "1",
            "root_domains-0-id": str(domain.pk),
            "root_domains-0-host": "example.com",
            "root_domains-0-DELETE": "on",
        }
        formset = RootDomainFormSetUpdate(
            data, instance=citation_source, prefix="root_domains"
        )
        assert formset.is_valid(), formset.errors

        request = request_factory.post("/")
        request.user = superuser
        admin_instance.save_formset(request, form=None, formset=formset, change=True)

        assert not CitationSourceRootDomain.objects.filter(pk=domain.pk).exists()

    def test_inline_hidden_on_child(
        self, admin_instance, request_factory, superuser, citation_source_with_parent
    ):
        request = request_factory.get("/")
        request.user = superuser
        inlines = admin_instance.get_inline_instances(
            request, obj=citation_source_with_parent
        )
        assert not any(
            isinstance(inline, CitationSourceRootDomainInline) for inline in inlines
        )

    def test_inline_shown_on_root(
        self, admin_instance, request_factory, superuser, citation_source
    ):
        request = request_factory.get("/")
        request.user = superuser
        inlines = admin_instance.get_inline_instances(request, obj=citation_source)
        assert any(
            isinstance(inline, CitationSourceRootDomainInline) for inline in inlines
        )

    def test_inline_shown_on_add_form(self, admin_instance, request_factory, superuser):
        request = request_factory.get("/")
        request.user = superuser
        inlines = admin_instance.get_inline_instances(request, obj=None)
        assert any(
            isinstance(inline, CitationSourceRootDomainInline) for inline in inlines
        )
