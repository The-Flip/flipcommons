"""Markdown rendering pipeline.

Converts markdown text (containing ``[[type:ref]]`` wikilinks) to
sanitized HTML. The wikilink-rendering helpers (``render_all_links``,
``link_preview``) live here too because they're consumed almost
exclusively by the markdown pipeline; non-markdown consumers that need
to walk the renderer registry import from
:mod:`apps.core.wikilinks` directly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import unescape
from typing import TYPE_CHECKING, Any

import nh3
from django.db import models
from django.utils.html import strip_tags
from django.utils.safestring import mark_safe
from markdown_it import MarkdownIt

from apps.core.markdown.field import get_markdown_fields

if TYPE_CHECKING:
    from apps.core.wikilinks import LinkType

# CommonMark-compliant markdown parser.
# - linkify: auto-link bare URLs during parsing (structure-aware, won't
#   linkify inside code blocks or existing links)
# - breaks: single newlines become <br> (equiv. to Python-Markdown's nl2br)
# - typographer + smartquotes/replacements: smart quotes, em dashes, ellipsis
#   (equiv. to Python-Markdown's smarty)
# - fenced code blocks are built into the commonmark preset
_md = MarkdownIt(
    "commonmark", {"linkify": True, "breaks": True, "typographer": True}
).enable(["linkify", "replacements", "smartquotes", "table", "strikethrough"])

# Allowed HTML tags for markdown rendering
ALLOWED_TAGS = {
    "p",
    "br",
    "strong",
    "em",
    "s",
    "ul",
    "ol",
    "li",
    "code",
    "pre",
    "blockquote",
    "a",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "img",
    "hr",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "figure",
    "figcaption",
    "sup",
}

# Allowed attributes per tag
ALLOWED_ATTRIBUTES = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title"},
    "code": {"class"},
    "pre": {"class"},
    "th": {"align"},
    "td": {"align"},
    "sup": {"data-cite-id", "data-cite-index", "tabindex", "role"},
}

# Regex for task list items: matches <li> followed by optional <p>, then [ ], [  ], [], [x], or [X]
# Group 1: optional whitespace+<p> (for blank-line-separated list items)
# Group 2: the check character to determine checked state (spaces or empty = unchecked)
_TASK_LIST_RE = re.compile(r"<li>(\s*<p>)?\s*\[( *|[xX])\]")


def _convert_task_list_items(html: str) -> str:
    """Convert task list markers in <li> tags to checkbox HTML.

    After markdown and nh3 processing, literal [ ] and [x] text inside <li> tags
    is converted to checkbox inputs. Each checkbox gets a sequential
    data-checkbox-index attribute for JavaScript targeting.

    This runs AFTER nh3 sanitization, so the injected <input> elements are
    trusted server code, not user-supplied HTML.
    """
    counter = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal counter
        idx = counter
        counter += 1
        p_tag = (
            match.group(1) or ""
        )  # Preserve <p> if present (blank-line-separated items)
        check_char = match.group(2)
        checked_attr = " checked" if check_char in ("x", "X") else ""
        return (
            f'<li class="task-list-item">{p_tag}'
            f'<input type="checkbox"{checked_attr} data-checkbox-index="{idx}" disabled>'
        )

    return _TASK_LIST_RE.sub(_replace, html)


# ---------------------------------------------------------------------------
# Wikilink → markdown-link rendering (runs BEFORE markdown processing)
# ---------------------------------------------------------------------------


def render_all_links(
    text: str,
    base_url: str = "",
    plain_text: bool = False,
    metadata_out: list[dict[str, Any]] | None = None,
) -> str:
    """Convert all [[type:ref]] links in text to markdown links.

    Handles both storage format (primary path) and authoring format
    (defense-in-depth for unconverted content).

    Missing targets render as ``*[broken link]*`` (or ``[broken link]``
    in plain-text mode).

    Args:
        text: Content containing ``[[type:ref]]`` links.
        base_url: When provided, prepend to URLs to make them absolute.
        plain_text: When ``True``, render just the label with no link
            syntax.  Useful for short preview snippets where markdown
            links would be truncated.
        metadata_out: When provided, link types with a ``collect_metadata``
            callback append structured dicts to this list (one per unique
            resolved object).
    """
    from apps.core.wikilinks import get_enabled_link_types, get_patterns

    for lt in get_enabled_link_types():
        pats = get_patterns(lt)
        if lt.public_id_field is not None:
            text = _render_by_id(
                text, lt, pats["storage"], base_url, plain_text, metadata_out
            )
            text = _render_by_public_id(
                text, lt, pats["authoring"], base_url, plain_text
            )
        else:
            text = _render_by_id(
                text, lt, pats["id"], base_url, plain_text, metadata_out
            )
    return text


def _format_link(
    lt: LinkType, obj: models.Model | None, base_url: str, plain_text: bool
) -> str:
    """Format a single resolved link as markdown or plain text."""
    if obj is None:
        return "[broken link]" if plain_text else "*[broken link]*"
    label = lt.resolve_label(obj)
    if plain_text:
        return label
    url = lt.resolve_url(obj)
    if base_url and not url.startswith(("http://", "https://")):
        url = base_url + url
    return f"[{label}]({url})"


def _render_by_id(
    text: str,
    lt: LinkType,
    pattern: re.Pattern[str],
    base_url: str = "",
    plain_text: bool = False,
    metadata_out: list[dict[str, Any]] | None = None,
) -> str:
    """Render [[type:id:N]] or [[type:N]] links by batch PK lookup."""
    matches = list(pattern.finditer(text))
    if not matches:
        return text

    model = lt.get_model()
    ids = [int(m.group(1)) for m in matches]
    qs = model.objects.filter(pk__in=ids)
    if lt.select_related:
        qs = qs.select_related(*lt.select_related)
    if lt.prefetch_related:
        qs = qs.prefetch_related(*lt.prefetch_related)
    by_id = {obj.pk: obj for obj in qs}

    # Build unique-ID → index mapping in order of first appearance
    # (for format_link renderers that need sequential numbering).
    index_by_id: dict[int, int] = {}
    if lt.format_link:
        for match in matches:
            obj_id = int(match.group(1))
            if obj_id not in index_by_id:
                index_by_id[obj_id] = len(index_by_id) + 1

    # Collect metadata for each unique resolved object (if requested).
    if metadata_out is not None and lt.collect_metadata:
        for obj_id, index in index_by_id.items():
            obj = by_id.get(obj_id)
            if obj is not None:
                metadata_out.append(lt.collect_metadata(obj, index))

    result = text
    for match in reversed(matches):
        obj_id = int(match.group(1))
        obj = by_id.get(obj_id)
        if lt.format_link:
            replacement = lt.format_link(obj, index_by_id[obj_id], base_url, plain_text)
        else:
            replacement = _format_link(lt, obj, base_url, plain_text)
        result = result[: match.start()] + replacement + result[match.end() :]
    return result


def _render_by_public_id(
    text: str,
    lt: LinkType,
    pattern: re.Pattern[str],
    base_url: str = "",
    plain_text: bool = False,
) -> str:
    """Render ``[[type:public_id]]`` links by batch lookup keyed on
    ``public_id_field`` (defense-in-depth — most authored content is in
    storage form by save time)."""
    matches = list(pattern.finditer(text))
    if not matches:
        return text

    model = lt.get_model()
    raw_values = [m.group(1) for m in matches]

    if lt.public_id_field is None:
        raise ValueError(f"LinkType '{lt.name}' is not public-id-based")
    by_key: dict[str, models.Model]
    if lt.authoring_lookup:
        by_key = lt.authoring_lookup(model, raw_values)
    else:
        qs = model.objects.filter(**{f"{lt.public_id_field}__in": raw_values})
        if lt.select_related:
            qs = qs.select_related(*lt.select_related)
        by_key = {getattr(obj, lt.public_id_field): obj for obj in qs}

    result = text
    for match in reversed(matches):
        key = match.group(1)
        obj = by_key.get(key)
        replacement = _format_link(lt, obj, base_url, plain_text)
        result = result[: match.start()] + replacement + result[match.end() :]
    return result


def link_preview(content: str, max_len: int = 30) -> str:
    """Truncate and sanitize text for use inside a markdown link label.

    Strips brackets (which would break ``[label](url)`` syntax) and
    collapses whitespace so the preview reads cleanly inline.
    """
    preview = content.replace("[", "").replace("]", "")
    preview = " ".join(preview.split())
    if len(preview) > max_len:
        preview = preview[:max_len] + "..."
    return preview


# ---------------------------------------------------------------------------
# Markdown → HTML pipeline
# ---------------------------------------------------------------------------


# ``metadata_out`` dicts are free-form: each link type's ``collect_metadata``
# callback defines its own key set and core never inspects them, so a TypedDict
# would lock in a shape core has no business enforcing.
def render_markdown_html(
    text: str | None, metadata_out: list[dict[str, Any]] | None = None
) -> str:
    """Convert markdown text to sanitized HTML.

    Full pipeline: wiki links -> markdown (with linkify) -> nh3 -> checkboxes.

    Args:
        text: Raw markdown text (may contain ``[[type:ref]]`` links).
        metadata_out: When provided, passed to ``render_all_links`` so
            link types with ``collect_metadata`` can append structured data.

    Returns:
        Sanitized HTML ``SafeString``, safe for direct use in templates.
    """
    if not text:
        return ""
    # Convert [[type:ref]] links to markdown links (before markdown processing)
    text = render_all_links(text, metadata_out=metadata_out)
    # Convert markdown to HTML (bare URLs are auto-linked during parsing)
    html = _md.render(text)
    # Sanitize to prevent XSS
    safe_html = nh3.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES)
    # Convert task list markers to checkboxes (after sanitization for security)
    return mark_safe(_convert_task_list_items(safe_html))  # noqa: S308 — HTML sanitized by nh3


def _html_to_plain(html: str) -> str:
    """Flatten rendered, sanitized HTML to a single whitespace-normalized line.

    markdown-it emits a trailing newline after each block token (preserved
    through sanitization), so collapsing whitespace after tag removal keeps
    block boundaries — list items and paragraphs separate rather than
    concatenating into ``onetwo`` — while inline tags drop without a spurious
    separator (``Williams</a>.`` → ``Williams.``). Entities are decoded
    *after* tag stripping so escaped markup (``&lt;script&gt;``) can't
    reintroduce tags.
    """
    return " ".join(unescape(strip_tags(html)).split())


def render_markdown_plain(text: str | None) -> str:
    """Render markdown text to clean, single-line plain prose.

    Resolves ``[[type:ref]]`` tokens to their labels and flattens all
    markdown/HTML structure, producing a whitespace-normalized single line
    suitable for ``<meta name="description">`` and machine-readable
    ``description`` fields. Built on :func:`render_markdown_html` so token
    resolution, sanitization and entity handling stay identical to the
    rendered HTML.
    """
    return _html_to_plain(render_markdown_html(text))


@dataclass(frozen=True, slots=True)
class RenderedField:
    """Rendered markdown output for a single field.

    ``citations`` stays as ``list[dict]`` because link types are extensible
    and ``apps.core`` has no business naming provenance-layer schemas (see
    ``render_markdown_html`` note). Callers validate citations into their
    own schemas via ``Schema.model_validate(...)`` at the boundary.

    ``plain`` is the flattened single-line projection of ``html``, computed
    once here so consumers (meta descriptions, machine-readable
    ``description`` fields) don't re-render the markdown.
    """

    html: str
    plain: str = ""
    citations: list[dict[str, Any]] = field(default_factory=list)


def render_markdown_field(obj: models.Model, field_name: str) -> RenderedField:
    """Render one markdown field on *obj* to HTML + plain text + citations.

    Returns empty ``RenderedField`` if the field's raw value is blank.
    """
    citations: list[dict[str, Any]] = []
    html = render_markdown_html(getattr(obj, field_name, ""), metadata_out=citations)
    return RenderedField(html=html, plain=_html_to_plain(html), citations=citations)


# Return value mixes rendered HTML strings and free-form metadata dicts
# (see ``render_markdown_html`` note); callers spread this into API payloads.
def render_markdown_fields(
    obj: models.Model,
) -> dict[str, str | list[dict[str, Any]]]:
    """Return ``{field}_html`` rendered values for all MarkdownField instances on *obj*.

    Designed for use with ``**`` spread in API serialization dicts::

        return {
            "name": obj.name,
            "description": obj.description,
            **render_markdown_fields(obj),
        }
    """
    result: dict[str, str | list[dict[str, Any]]] = {}
    for field_name in get_markdown_fields(type(obj)):
        citations: list[dict[str, Any]] = []
        result[f"{field_name}_html"] = render_markdown_html(
            getattr(obj, field_name, ""), metadata_out=citations
        )
        if citations:
            result[f"{field_name}_citations"] = citations
    return result
