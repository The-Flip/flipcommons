"""Tests for the markdown rendering pipeline, conversion, and reference syncing."""

from typing import Any

import pytest
from django.core.exceptions import ValidationError

from apps.citation.test_factories import make_citation_link, make_citation_source
from apps.core.markdown import (
    convert_authoring_to_storage,
    convert_storage_to_authoring,
    render_all_links,
    render_markdown_fields,
    render_markdown_html,
    render_markdown_plain,
)
from apps.core.markdown.references import sync_references
from apps.core.models import RecordReference
from apps.provenance.test_factories import make_citation_instance


@pytest.fixture
def manufacturer(db):
    from apps.catalog.models import Manufacturer

    return Manufacturer.objects.create(name="Williams", slug="williams")


@pytest.fixture
def system(db, manufacturer):
    from apps.catalog.models import System

    return System.objects.create(
        name="WPC-95", slug="wpc-95", manufacturer=manufacturer
    )


@pytest.fixture
def citation_source(db):
    return make_citation_source(
        name="The Encyclopedia of Pinball",
        source_type="book",
        author="Jeff Lawton",
        year=2001,
    )


@pytest.fixture
def citation_source_with_links(citation_source):
    make_citation_link(
        citation_source=citation_source,
        url="https://example.com/archive",
        label="Archive scan",
        link_type="archive",
    )
    return citation_source


@pytest.fixture
def citation_instance(citation_source):
    return make_citation_instance(citation_source=citation_source, locator="p. 30")


class TestRenderMarkdownHtml:
    def test_empty_string(self):
        assert render_markdown_html("") == ""

    def test_none_input(self):
        assert render_markdown_html(None) == ""

    def test_bold(self):
        result = render_markdown_html("**bold**")
        assert "<strong>bold</strong>" in result

    def test_italic(self):
        result = render_markdown_html("*italic*")
        assert "<em>italic</em>" in result

    def test_link(self):
        result = render_markdown_html("[text](https://example.com)")
        assert 'href="https://example.com"' in result
        assert ">text</a>" in result

    def test_unordered_list(self):
        result = render_markdown_html("- item 1\n- item 2")
        assert "<ul>" in result
        assert "<li>item 1</li>" in result

    def test_heading(self):
        result = render_markdown_html("## Heading")
        assert "<h2>Heading</h2>" in result

    def test_xss_script_stripped(self):
        result = render_markdown_html('<script>alert("xss")</script>')
        assert "<script>" not in result
        assert "alert" not in result

    def test_xss_onerror_stripped(self):
        result = render_markdown_html('<img src=x onerror="alert(1)">')
        assert "onerror" not in result

    def test_auto_linkify(self):
        result = render_markdown_html("Visit https://example.com today")
        assert 'href="https://example.com"' in result

    def test_line_breaks(self):
        result = render_markdown_html("line 1\nline 2")
        assert "<br>" in result

    def test_task_list_unchecked(self):
        result = render_markdown_html("- [ ] todo")
        assert 'type="checkbox"' in result
        assert "checked" not in result

    def test_task_list_checked(self):
        result = render_markdown_html("- [x] done")
        assert 'type="checkbox"' in result
        assert "checked" in result

    def test_table(self):
        md = "| A | B |\n|---|---|\n| 1 | 2 |"
        result = render_markdown_html(md)
        assert "<table>" in result
        assert "<td>" in result

    def test_strikethrough(self):
        result = render_markdown_html("~~deleted~~")
        assert "<s>deleted</s>" in result

    @pytest.mark.django_db
    def test_broken_link_renders(self):
        result = render_markdown_html("See [[manufacturer:id:99999]]")
        assert "broken link" in result

    @pytest.mark.django_db
    def test_metadata_out_collects_citations(self):
        src = make_citation_source(
            name="Source Book", source_type="book", author="A. Author"
        )
        ci = make_citation_instance(citation_source=src, locator="ch. 3")
        metadata: list[dict[str, Any]] = []
        html = render_markdown_html(f"Fact.[[cite:id:{ci.pk}]]", metadata_out=metadata)
        assert "data-cite-id" in html
        assert len(metadata) == 1
        assert metadata[0]["source_name"] == "Source Book"

    def test_metadata_out_default_none(self):
        """metadata_out defaults to None; existing callers unaffected."""
        result = render_markdown_html("plain text")
        assert "plain text" in result


class TestRenderMarkdownFields:
    def test_returns_html_for_markdown_fields(self):
        from apps.catalog.models import Manufacturer

        mfr = Manufacturer(name="Test", slug="test", description="**bold**")
        result = render_markdown_fields(mfr)
        assert "description_html" in result
        assert "<strong>bold</strong>" in result["description_html"]

    def test_empty_description(self):
        from apps.catalog.models import Manufacturer

        mfr = Manufacturer(name="Test", slug="test", description="")
        result = render_markdown_fields(mfr)
        assert result["description_html"] == ""

    def test_person_description_field(self):
        from apps.catalog.models import Person

        person = Person(name="Pat", slug="pat", description="*italic*")
        result = render_markdown_fields(person)
        assert "description_html" in result
        assert "<em>italic</em>" in result["description_html"]

    def test_no_markdown_fields(self):
        from apps.catalog.models import LocationAlias

        alias = LocationAlias(value="USA")
        result = render_markdown_fields(alias)
        assert result == {}

    @pytest.mark.django_db
    def test_citations_key_included(self):
        from apps.catalog.models import Manufacturer

        src = make_citation_source(name="Book", source_type="book")
        ci = make_citation_instance(citation_source=src, locator="p. 1")
        mfr = Manufacturer(
            name="Test", slug="test", description=f"Info.[[cite:id:{ci.pk}]]"
        )
        result = render_markdown_fields(mfr)
        citations = result["description_citations"]
        assert isinstance(citations, list)
        assert citations
        citation = citations[0]
        assert isinstance(citation, dict)
        assert "description_html" in result
        assert "description_citations" in result
        assert len(citations) == 1
        assert citation["id"] == ci.pk

    def test_no_citations_key_when_empty(self):
        from apps.catalog.models import Manufacturer

        mfr = Manufacturer(name="Test", slug="test", description="No citations here")
        result = render_markdown_fields(mfr)
        assert "description_citations" not in result


class TestRenderAllLinks:
    def test_render_storage_format(self, manufacturer):
        text = f"Made by [[manufacturer:id:{manufacturer.pk}]]"
        result = render_all_links(text)
        assert "[Williams](/manufacturers/williams)" in result

    def test_render_authoring_format(self, manufacturer):
        text = "Made by [[manufacturer:williams]]"
        result = render_all_links(text)
        assert "[Williams](/manufacturers/williams)" in result

    def test_render_broken_link(self, db):
        text = "See [[manufacturer:id:99999]]"
        result = render_all_links(text)
        assert "*[broken link]*" in result

    def test_render_broken_link_plain_text(self, db):
        text = "See [[manufacturer:id:99999]]"
        result = render_all_links(text, plain_text=True)
        assert "[broken link]" in result
        assert "*" not in result

    def test_render_with_base_url(self, manufacturer):
        text = f"See [[manufacturer:id:{manufacturer.pk}]]"
        result = render_all_links(text, base_url="https://flipcommons.org")
        assert "https://flipcommons.org/manufacturers/williams" in result

    def test_render_multiple_links(self, manufacturer, system):
        text = (
            f"Made by [[manufacturer:id:{manufacturer.pk}]] "
            f"on [[system:id:{system.pk}]]"
        )
        result = render_all_links(text)
        assert "[Williams](/manufacturers/williams)" in result
        assert "[WPC-95](/systems/wpc-95)" in result


class TestRenderMarkdownPlain:
    def test_empty_string(self):
        assert render_markdown_plain("") == ""

    def test_none_input(self):
        assert render_markdown_plain(None) == ""

    def test_strips_bold(self):
        result = render_markdown_plain("**bold** text")
        assert result == "bold text"

    def test_strips_heading_syntax(self):
        result = render_markdown_plain("# Heading")
        assert result == "Heading"

    def test_resolves_token_to_label(self, manufacturer):
        result = render_markdown_plain(f"Made by [[manufacturer:id:{manufacturer.pk}]]")
        assert result == "Made by Williams"
        assert "[[" not in result
        assert "(" not in result  # no leftover markdown link syntax

    def test_broken_link_renders_plain_marker(self, db):
        result = render_markdown_plain("See [[manufacturer:id:99999]]")
        assert result == "See [broken link]"
        assert "*" not in result

    def test_decodes_html_entities(self):
        result = render_markdown_plain("Tom & Jerry")
        assert result == "Tom & Jerry"
        assert "&amp;" not in result

    def test_no_tags_leak(self):
        result = render_markdown_plain("**bold** and *italic*")
        assert "<" not in result
        assert ">" not in result

    def test_list_items_separated_not_concatenated(self):
        # Block boundaries must separate; never collapse to "onetwothree".
        result = render_markdown_plain("- one\n- two\n- three")
        assert result == "one two three"

    def test_paragraphs_collapse_to_single_separated_line(self):
        result = render_markdown_plain("First para.\n\nSecond para.")
        assert result == "First para. Second para."


class TestAuthoringToStorage:
    def test_converts_slug_to_id(self, manufacturer):
        result = convert_authoring_to_storage("See [[manufacturer:williams]]")
        assert f"[[manufacturer:id:{manufacturer.pk}]]" in result

    def test_invalid_slug_raises_validation_error(self, db):
        with pytest.raises(ValidationError, match="not found"):
            convert_authoring_to_storage("See [[manufacturer:nonexistent]]")

    def test_empty_string(self):
        assert convert_authoring_to_storage("") == ""

    def test_no_links_unchanged(self):
        text = "Just plain text"
        assert convert_authoring_to_storage(text) == text


class TestStorageToAuthoring:
    def test_converts_id_to_slug(self, manufacturer):
        text = f"See [[manufacturer:id:{manufacturer.pk}]]"
        result = convert_storage_to_authoring(text)
        assert "[[manufacturer:williams]]" in result

    def test_broken_link_kept_as_storage(self, db):
        text = "See [[manufacturer:id:99999]]"
        result = convert_storage_to_authoring(text)
        assert "[[manufacturer:id:99999]]" in result

    def test_empty_string(self):
        assert convert_storage_to_authoring("") == ""


class TestSyncReferences:
    def test_creates_references(self, manufacturer, system):
        text = (
            f"Links to [[manufacturer:id:{manufacturer.pk}]] "
            f"and [[system:id:{system.pk}]]"
        )
        # Use system as the source (it has a MarkdownField)
        system.description = text
        sync_references(system)
        refs = RecordReference.objects.all()
        assert refs.count() == 2

    def test_removes_stale_references(self, manufacturer, system):
        # First sync with a link
        text = f"Links to [[manufacturer:id:{manufacturer.pk}]]"
        system.description = text
        sync_references(system)
        assert RecordReference.objects.count() == 1

        # Second sync without the link
        system.description = "No links here"
        sync_references(system)
        assert RecordReference.objects.count() == 0

    def test_a_second_markdown_field_does_not_evict_the_first(
        self, manufacturer, system, monkeypatch
    ) -> None:
        """Reconciliation is per source, so it must see every field at once.

        Read one field at a time and the second pass treats the first field's
        links as stale and deletes them.
        """
        monkeypatch.setattr(
            "apps.core.markdown.field.get_markdown_fields",
            lambda model: ["description", "name"],
        )
        system.description = f"[[manufacturer:id:{manufacturer.pk}]]"
        system.name = f"[[system:id:{system.pk}]]"
        sync_references(system)
        assert RecordReference.objects.count() == 2

    def test_idempotent(self, manufacturer, system):
        text = f"Links to [[manufacturer:id:{manufacturer.pk}]]"
        system.description = text
        sync_references(system)
        sync_references(system)
        assert RecordReference.objects.count() == 1


class TestCitationLinkType:
    def test_cite_registered(self):
        from apps.core.wikilinks import get_link_type

        lt = get_link_type("cite")
        assert lt is not None
        assert lt.public_id_field == "slug"
        assert lt.format_link is not None

    def test_render_single_citation(self, citation_instance):
        text = f"Production was 4,000 units.[[cite:id:{citation_instance.pk}]]"
        result = render_all_links(text)
        pk = citation_instance.pk
        assert (
            f'<sup data-cite-id="{pk}" data-cite-index="1"'
            f' tabindex="0" role="button">[1]</sup>' in result
        )
        assert "[[cite:" not in result

    def test_render_multiple_citations(self, citation_source):
        ci1 = make_citation_instance(citation_source=citation_source, locator="p. 30")
        ci2 = make_citation_instance(citation_source=citation_source, locator="p. 83")
        text = f"First fact.[[cite:id:{ci1.pk}]] Second fact.[[cite:id:{ci2.pk}]]"
        result = render_all_links(text)
        assert (
            f'<sup data-cite-id="{ci1.pk}" data-cite-index="1"'
            f' tabindex="0" role="button">[1]</sup>' in result
        )
        assert (
            f'<sup data-cite-id="{ci2.pk}" data-cite-index="2"'
            f' tabindex="0" role="button">[2]</sup>' in result
        )

    def test_duplicate_citation_same_number(self, citation_instance):
        pk = citation_instance.pk
        text = f"First mention.[[cite:id:{pk}]] Second mention.[[cite:id:{pk}]]"
        result = render_all_links(text)
        # Both should be [1], not [1] and [2]
        assert result.count("[1]") == 2
        assert "[2]" not in result

    def test_render_broken_citation(self, db):
        text = "Cited.[[cite:id:99999]]"
        result = render_all_links(text)
        assert "<sup>[?]</sup>" in result

    def test_render_plain_text(self, citation_instance):
        text = f"Cited.[[cite:id:{citation_instance.pk}]]"
        result = render_all_links(text, plain_text=True)
        assert result == "Cited.[1]"

    def test_render_broken_plain_text(self, db):
        text = "Cited.[[cite:id:99999]]"
        result = render_all_links(text, plain_text=True)
        assert "[?]" in result
        assert "<sup>" not in result

    def test_mixed_citations_and_entity_links(self, manufacturer, citation_instance):
        text = (
            f"Made by [[manufacturer:id:{manufacturer.pk}]]."
            f"[[cite:id:{citation_instance.pk}]]"
        )
        result = render_all_links(text)
        assert "[Williams](/manufacturers/williams)" in result
        assert (
            f'<sup data-cite-id="{citation_instance.pk}" data-cite-index="1"'
            f' tabindex="0" role="button">[1]</sup>' in result
        )

    def test_sync_references_for_citations(self, citation_instance, system):
        text = f"Cited.[[cite:id:{citation_instance.pk}]]"
        system.description = text
        sync_references(system)
        refs = RecordReference.objects.all()
        assert refs.count() == 1

    def test_cite_survives_html_pipeline(self, citation_instance):
        text = f"Production was 4,000 units.[[cite:id:{citation_instance.pk}]]"
        html = render_markdown_html(text)
        pk = citation_instance.pk
        assert f'data-cite-id="{pk}"' in html
        assert 'data-cite-index="1"' in html
        assert 'tabindex="0"' in html
        assert 'role="button"' in html
        assert "[1]" in html


class TestCiteRegularized:
    """cite is a normal public-id wikilink type keyed on CitationInstance.slug:
    [[cite:<slug>]] authoring ↔ [[cite:id:<pk>]] storage."""

    def test_storage_to_authoring_uses_slug(self, citation_instance):
        text = f"Fact.[[cite:id:{citation_instance.pk}]]"
        result = convert_storage_to_authoring(text)
        assert result == f"Fact.[[cite:{citation_instance.slug}]]"

    def test_authoring_to_storage_resolves_slug(self, citation_instance):
        text = f"Fact.[[cite:{citation_instance.slug}]]"
        result = convert_authoring_to_storage(text)
        assert result == f"Fact.[[cite:id:{citation_instance.pk}]]"

    def test_roundtrip_unchanged(self, citation_instance):
        storage = f"Fact.[[cite:id:{citation_instance.pk}]]"
        assert (
            convert_authoring_to_storage(convert_storage_to_authoring(storage))
            == storage
        )

    def test_unknown_slug_raises_on_conversion(self, db):
        with pytest.raises(ValidationError, match="not found"):
            convert_authoring_to_storage("Fact.[[cite:nosuchslug]]")

    def test_storage_form_footnotes(self, citation_instance):
        result = render_all_links(f"Fact.[[cite:id:{citation_instance.pk}]]")
        assert f'data-cite-id="{citation_instance.pk}"' in result
        assert "<sup" in result

    def test_authoring_form_does_not_footnote(self, citation_instance):
        # A bare authoring [[cite:slug]] reaches the renderer only as
        # defense-in-depth (stored text is always storage form); it renders as a
        # plain/broken link via _render_by_public_id, never a <sup> footnote.
        result = render_all_links(f"Fact.[[cite:{citation_instance.slug}]]")
        assert "data-cite-id" not in result
        assert "<sup" not in result


class TestMetadataCollection:
    """Tests for render_all_links metadata_out collection."""

    def test_collects_citation_metadata(self, citation_source_with_links):
        ci = make_citation_instance(
            citation_source=citation_source_with_links,
            locator="p. 42",
            quote="The flippers were revolutionary.",
        )
        text = f"Cited.[[cite:id:{ci.pk}]]"
        metadata: list[dict[str, Any]] = []
        render_all_links(text, metadata_out=metadata)
        assert len(metadata) == 1
        entry = metadata[0]
        assert entry["id"] == ci.pk
        assert entry["index"] == 1
        assert entry["source_name"] == "The Encyclopedia of Pinball"
        assert entry["source_type"] == "book"
        assert entry["author"] == "Jeff Lawton"
        assert entry["year"] == 2001
        assert entry["locator"] == "p. 42"
        assert entry["quote"] == "The flippers were revolutionary."
        assert len(entry["links"]) == 1
        assert entry["links"][0]["url"] == "https://example.com/archive"
        assert entry["links"][0]["link_type"] == "archive"
        assert entry["links"][0]["display_name"] == "Archive scan"

    def test_metadata_deduplicated_by_pk(self, citation_instance):
        pk = citation_instance.pk
        text = f"First.[[cite:id:{pk}]] Second.[[cite:id:{pk}]]"
        metadata: list[dict[str, Any]] = []
        render_all_links(text, metadata_out=metadata)
        assert len(metadata) == 1
        assert metadata[0]["id"] == pk

    def test_metadata_ordered_by_first_appearance(self, citation_source):
        ci1 = make_citation_instance(citation_source=citation_source, locator="p. 10")
        ci2 = make_citation_instance(citation_source=citation_source, locator="p. 20")
        text = f"First.[[cite:id:{ci1.pk}]] Second.[[cite:id:{ci2.pk}]]"
        metadata: list[dict[str, Any]] = []
        render_all_links(text, metadata_out=metadata)
        assert len(metadata) == 2
        assert metadata[0]["index"] == 1
        assert metadata[0]["id"] == ci1.pk
        assert metadata[1]["index"] == 2
        assert metadata[1]["id"] == ci2.pk

    def test_no_metadata_when_none(self, citation_instance):
        """metadata_out=None (default) doesn't break anything."""
        text = f"Cited.[[cite:id:{citation_instance.pk}]]"
        result = render_all_links(text)
        assert "data-cite-id" in result

    def test_no_metadata_for_entity_links(self, manufacturer):
        """Only link types with collect_metadata produce metadata."""
        text = f"See [[manufacturer:id:{manufacturer.pk}]]"
        metadata: list[dict[str, Any]] = []
        render_all_links(text, metadata_out=metadata)
        assert len(metadata) == 0
