from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.apps import AppConfig

if TYPE_CHECKING:
    from apps.citation.models import CitationInstance


def _format_citation_link(
    obj: CitationInstance | None, index: int, base_url: str, plain_text: bool
) -> str:
    """Render a citation marker as a superscript footnote number."""
    if obj is None:
        return "[?]" if plain_text else "<sup>[?]</sup>"
    if plain_text:
        return f"[{index}]"
    return (
        f'<sup data-cite-id="{obj.pk}" data-cite-index="{index}"'
        f' tabindex="0" role="button">[{index}]</sup>'
    )


# Return is dict[str, Any] (not a TypedDict) because LinkType.collect_metadata
# is typed as ``Callable[[Any, int], dict]`` in apps.core.wikilinks.types; a
# TypedDict isn't assignable to a bare ``dict`` parameter under strict mypy.
def _collect_citation_metadata(obj: CitationInstance, index: int) -> dict[str, Any]:
    """Collect structured metadata for a citation instance.

    Called by core's render pipeline via the collect_metadata callback.
    Core never inspects the returned dict — this is citation-owned logic.
    """
    from apps.citation.deep_links import deep_linked_url

    return {
        "id": obj.pk,
        "index": index,
        "source_name": obj.citation_source.name,
        "source_type": obj.citation_source.source_type,
        "author": obj.citation_source.author,
        "year": obj.citation_source.year,
        "locator": obj.locator,
        "links": [
            {
                "url": deep_linked_url(obj.citation_source, obj.locator, link.url),
                "label": link.label,
            }
            for link in obj.citation_source.links.all()
        ],
    }


def _citation_authoring_url(obj: CitationInstance) -> str:
    """Degrade an authoring-form ``[[cite:slug]]`` to a hrefless link.

    Footnotes are rendered off the *storage* (``[[cite:id:N]]``) pattern via
    ``format_link``; an authoring-form cite only reaches the generic
    ``_render_by_public_id`` path as defense-in-depth (stored text is always
    storage form). CitationInstance has no URL identity, so without this the
    generic ``resolve_url`` would ``AttributeError`` on a missing ``public_id``.
    Return empty so it renders as a plain, non-footnote link instead.
    """
    return ""


class CitationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.citation"
    verbose_name = "Citation"

    def ready(self) -> None:
        from apps.core.wikilinks import (
            LinkType,
            PickerType,
            register,
            register_picker,
        )

        from . import (
            authz,  # noqa: F401  # registers authz rules at startup
            scheme_validation,  # noqa: F401  # registers the scheme check
        )

        register(
            LinkType(
                name="cite",
                model_path="citation.CitationInstance",
                # cite is a normal public-id wikilink type keyed on the durable
                # CitationInstance.slug: [[cite:<slug>]] authoring ↔
                # [[cite:id:<pk>]] storage. format_link/collect_metadata still
                # drive footnote rendering off the storage (id) pattern.
                public_id_field="slug",
                # Inline footnotes are never emitted into the public export dump.
                export_inline=False,
                # Safe degrade for the never-hit authoring-form render path.
                get_url=_citation_authoring_url,
                format_link=_format_citation_link,
                collect_metadata=_collect_citation_metadata,
                # The parent ride-along feeds deep_linked_url (scheme lookup
                # via the root's identifier_key) without a per-cite query.
                select_related=("citation_source", "citation_source__parent"),
                prefetch_related=("citation_source__links",),
            )
        )
        # Citation is offered in the wikilink picker via the custom flow:
        # the frontend drives a multi-step source/locator selection; the
        # standard autocomplete query path (model + search fields) is unused.
        register_picker(
            PickerType(
                name="cite",
                label="Citation",
                description="Cite a source (book, web, magazine)",
                sort_order=1,
                flow="custom",
            )
        )
