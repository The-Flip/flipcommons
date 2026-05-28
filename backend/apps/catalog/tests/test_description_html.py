"""Tests for description_html in API responses."""

import pytest

from apps.catalog.models import Location, Manufacturer, System
from apps.core.models import RecordReference


@pytest.fixture
def client():
    from django.test import Client

    return Client()


@pytest.fixture
def manufacturer_with_description(db):
    return Manufacturer.objects.create(
        name="Williams",
        slug="williams",
        description="A **legendary** pinball manufacturer.",
    )


@pytest.fixture
def system_with_description(db):
    mfr, _ = Manufacturer.objects.get_or_create(
        slug="williams", defaults={"name": "Williams"}
    )
    return System.objects.create(
        name="WPC-95",
        slug="wpc-95",
        manufacturer=mfr,
        description="The final WPC generation.",
    )


class TestManufacturerDescriptionHtml:
    def test_detail_includes_description_html(
        self, client, manufacturer_with_description
    ):
        resp = client.get("/api/pages/manufacturer/williams")
        assert resp.status_code == 200
        data = resp.json()
        assert "html" in data["description"]
        assert "<strong>legendary</strong>" in data["description"]["html"]

    def test_empty_description_returns_empty_html(self, client, db):
        Manufacturer.objects.create(name="Stern", slug="stern")
        resp = client.get("/api/pages/manufacturer/stern")
        data = resp.json()
        assert data["description"]["html"] == ""

    @pytest.mark.django_db
    def test_entity_link_in_description(self, client, db):
        williams = Manufacturer.objects.create(name="Williams", slug="williams")
        System.objects.create(
            name="WPC-95",
            slug="wpc-95",
            manufacturer=williams,
            description=f"Made by [[manufacturer:id:{williams.pk}]].",
        )
        resp = client.get("/api/pages/system/wpc-95")
        data = resp.json()
        assert "/manufacturers/williams" in data["description"]["html"]
        assert "Williams" in data["description"]["html"]


class TestSystemDescriptionHtml:
    def test_detail_includes_description_html(self, client, system_with_description):
        resp = client.get("/api/pages/system/wpc-95")
        assert resp.status_code == 200
        data = resp.json()
        assert "html" in data["description"]
        assert data["description"]["html"] != ""

    def test_raw_description_also_present(self, client, system_with_description):
        resp = client.get("/api/pages/system/wpc-95")
        data = resp.json()
        assert data["description"]["text"] == "The final WPC generation."


@pytest.mark.django_db
class TestLocationDescriptionHtml:
    def test_detail_includes_description_html(self, client):
        Location.objects.create(
            location_path="usa",
            slug="usa",
            name="USA",
            location_type="country",
            description="A **federal** republic.",
        )
        resp = client.get("/api/pages/locations/usa")
        assert resp.status_code == 200
        data = resp.json()
        assert "<strong>federal</strong>" in data["description"]["html"]

    def test_entity_link_in_description(self, client):
        williams = Manufacturer.objects.create(name="Williams", slug="williams")
        Location.objects.create(
            location_path="usa",
            slug="usa",
            name="USA",
            location_type="country",
            description=f"Home of [[manufacturer:id:{williams.pk}]].",
        )
        resp = client.get("/api/pages/locations/usa")
        data = resp.json()
        # html resolves the link; text is round-tripped to authoring format.
        assert "/manufacturers/williams" in data["description"]["html"]
        assert "[[manufacturer:williams]]" in data["description"]["text"]


@pytest.mark.django_db
class TestDescriptionAuthoringFormat:
    """API responses return description text in authoring format for editing."""

    def test_storage_links_converted_to_authoring_in_text(self, client, db):
        """description.text returns [[type:slug]] not [[type:id:N]]."""
        williams = Manufacturer.objects.create(name="Williams", slug="williams")
        System.objects.create(
            name="WPC-95",
            slug="wpc-95",
            manufacturer=williams,
            description=f"Made by [[manufacturer:id:{williams.pk}]].",
        )
        resp = client.get("/api/pages/system/wpc-95")
        data = resp.json()
        # text field should have authoring format (slug-based)
        assert "[[manufacturer:williams]]" in data["description"]["text"]
        assert f"[[manufacturer:id:{williams.pk}]]" not in data["description"]["text"]
        # html field should still render the link correctly
        assert "/manufacturers/williams" in data["description"]["html"]

    def test_plain_text_description_unchanged(self, client, db):
        """Descriptions without links are returned as-is."""
        Manufacturer.objects.create(
            name="Stern", slug="stern", description="Modern manufacturer."
        )
        resp = client.get("/api/pages/manufacturer/stern")
        data = resp.json()
        assert data["description"]["text"] == "Modern manufacturer."

    def test_broken_link_kept_in_storage_format(self, client, db):
        """Links to deleted entities stay in storage format (graceful degradation)."""
        Manufacturer.objects.create(
            name="Stern",
            slug="stern",
            description="See [[manufacturer:id:99999]].",
        )
        resp = client.get("/api/pages/manufacturer/stern")
        data = resp.json()
        # Broken link stays in storage format since there's no slug to convert to
        assert "[[manufacturer:id:99999]]" in data["description"]["text"]


@pytest.mark.django_db
class TestDescriptionCitations:
    """API responses include inline citation metadata alongside rendered HTML."""

    def test_citations_present_in_response(self, client, db):
        from apps.citation.models import CitationSource, CitationSourceLink
        from apps.provenance.models import CitationInstance

        src = CitationSource.objects.create(
            name="The Complete Pinball Book",
            source_type="book",
            author="Marco Rossignoli",
            year=2002,
        )
        CitationSourceLink.objects.create(
            citation_source=src,
            url="https://example.com/book",
            label="Publisher",
            link_type="publisher",
        )
        ci = CitationInstance.objects.create(citation_source=src, locator="p. 150")

        Manufacturer.objects.create(
            name="Williams",
            slug="williams",
            description=f"Founded in 1943.[[cite:{ci.pk}]]",
        )
        resp = client.get("/api/pages/manufacturer/williams")
        assert resp.status_code == 200
        data = resp.json()

        citations = data["description"]["citations"]
        assert len(citations) == 1
        cite = citations[0]
        assert cite["id"] == ci.pk
        assert cite["index"] == 1
        assert cite["source_name"] == "The Complete Pinball Book"
        assert cite["source_type"] == "book"
        assert cite["author"] == "Marco Rossignoli"
        assert cite["year"] == 2002
        assert cite["locator"] == "p. 150"
        assert len(cite["links"]) == 1
        assert cite["links"][0]["url"] == "https://example.com/book"

    def test_empty_citations_when_no_citations(self, client, db):
        Manufacturer.objects.create(
            name="Stern", slug="stern", description="Modern manufacturer."
        )
        resp = client.get("/api/pages/manufacturer/stern")
        data = resp.json()
        assert data["description"]["citations"] == []


@pytest.mark.django_db
class TestDescriptionPlain:
    """API responses include a flattened, token-free `plain` projection."""

    def test_plain_strips_markdown(self, client):
        Manufacturer.objects.create(
            name="Williams",
            slug="williams",
            description="A **legendary** pinball manufacturer.",
        )
        resp = client.get("/api/pages/manufacturer/williams")
        data = resp.json()
        assert data["description"]["plain"] == "A legendary pinball manufacturer."

    def test_plain_resolves_links_to_labels(self, client):
        williams = Manufacturer.objects.create(name="Williams", slug="williams")
        System.objects.create(
            name="WPC-95",
            slug="wpc-95",
            manufacturer=williams,
            description=f"Made by [[manufacturer:id:{williams.pk}]].",
        )
        resp = client.get("/api/pages/system/wpc-95")
        data = resp.json()
        plain = data["description"]["plain"]
        assert plain == "Made by Williams."
        assert "[[" not in plain
        assert "<" not in plain

    def test_plain_empty_when_no_description(self, client):
        Manufacturer.objects.create(name="Stern", slug="stern")
        resp = client.get("/api/pages/manufacturer/stern")
        data = resp.json()
        assert data["description"]["plain"] == ""


@pytest.mark.django_db
class TestReferenceSync:
    def test_resolve_creates_references(self):
        """Resolving a manufacturer with links creates RecordReference rows."""
        from django.contrib.contenttypes.models import ContentType

        from apps.catalog.resolve import resolve_entity
        from apps.provenance.models import Claim, Source

        mfr = Manufacturer.objects.create(name="Williams", slug="williams")
        system = System.objects.create(name="WPC-95", slug="wpc-95", manufacturer=mfr)
        source = Source.objects.create(name="test", priority=100)
        Claim.objects.assert_claim(
            mfr,
            "description",
            f"Uses [[system:id:{system.pk}]].",
            source=source,
        )
        resolve_entity(mfr)

        mfr_ct = ContentType.objects.get_for_model(Manufacturer)
        refs = RecordReference.objects.filter(source_type=mfr_ct, source_id=mfr.pk)
        assert refs.count() == 1
        system_ct = ContentType.objects.get_for_model(System)
        ref = refs.first()
        assert ref is not None
        assert ref.target_type == system_ct
        assert ref.target_id == system.pk

    def test_blanked_field_cleans_up_references(self):
        """When a description is blanked, stale RecordReference rows are removed."""
        from django.contrib.contenttypes.models import ContentType

        from apps.catalog.resolve import resolve_entity
        from apps.provenance.models import Claim, Source

        mfr = Manufacturer.objects.create(name="Williams", slug="williams")
        system = System.objects.create(name="WPC-95", slug="wpc-95", manufacturer=mfr)
        source = Source.objects.create(name="test", priority=100)

        # Create a reference via description with a link
        Claim.objects.assert_claim(
            mfr,
            "description",
            f"Uses [[system:id:{system.pk}]].",
            source=source,
        )
        resolve_entity(mfr)
        mfr_ct = ContentType.objects.get_for_model(Manufacturer)
        assert (
            RecordReference.objects.filter(source_type=mfr_ct, source_id=mfr.pk).count()
            == 1
        )

        # Deactivate the claim so description resolves to blank
        Claim.objects.filter(
            content_type=mfr_ct, object_id=mfr.pk, field_name="description"
        ).update(is_active=False)
        resolve_entity(mfr)

        assert mfr.description == ""
        assert (
            RecordReference.objects.filter(source_type=mfr_ct, source_id=mfr.pk).count()
            == 0
        )


@pytest.mark.django_db
class TestApiPatchConversion:
    def test_patch_converts_authoring_to_storage(self, user):
        """API PATCH endpoint converts [[type:slug]] to [[type:id:N]]."""
        from django.test import Client

        mfr = Manufacturer.objects.create(name="Williams", slug="williams")
        system = System.objects.create(name="WPC-95", slug="wpc-95", manufacturer=mfr)

        client = Client()
        client.force_login(user)
        resp = client.patch(
            f"/api/manufacturers/{mfr.slug}/claims/",
            {"fields": {"description": "Uses [[system:wpc-95]]."}},
            content_type="application/json",
        )
        assert resp.status_code == 200

        from apps.provenance.models import Claim

        claim = Claim.objects.filter(
            object_id=mfr.pk, field_name="description", is_active=True
        ).first()
        assert claim is not None
        assert f"[[system:id:{system.pk}]]" in claim.value
