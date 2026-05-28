"""Markdown consumer package.

Turns markdown content into sanitized HTML and bridges markdown content
into the :class:`~apps.core.models.RecordReference` graph by parsing
wikilinks from saved content.

Layout:

- :mod:`render` — markdown→HTML pipeline + wikilink→markdown-link rendering.
- :mod:`field` — :class:`MarkdownField` and the conversion path that
  doesn't touch ``RecordReference``. Catalog model files import
  :class:`MarkdownField` from here.
- :mod:`references` — the markdown→\\ ``RecordReference`` bridge
  (``sync_references``, ``save_inline_markdown_field``). Save-path
  callers import directly from there; the bridge is intentionally not
  re-exported here so the dependency surface stays explicit.
"""

from apps.core.markdown.field import (
    MarkdownField,
    convert_authoring_to_storage,
    convert_storage_to_authoring,
    get_markdown_fields,
    prepare_markdown_claim_value,
)
from apps.core.markdown.render import (
    RenderedField,
    link_preview,
    render_all_links,
    render_markdown_field,
    render_markdown_fields,
    render_markdown_html,
    render_markdown_plain,
)

__all__ = [
    "MarkdownField",
    "RenderedField",
    "convert_authoring_to_storage",
    "convert_storage_to_authoring",
    "get_markdown_fields",
    "link_preview",
    "prepare_markdown_claim_value",
    "render_all_links",
    "render_markdown_field",
    "render_markdown_fields",
    "render_markdown_html",
    "render_markdown_plain",
]
