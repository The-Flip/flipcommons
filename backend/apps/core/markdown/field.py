"""Wikilink-aware authoring↔storage conversion for ``MarkdownField`` content.

The :class:`MarkdownField` storage class itself lives in
:mod:`apps.core.models.fields` (the models layer); it is imported here only so
:func:`get_markdown_fields` can introspect models for it. The conversion helpers
below are wikilink-aware (they lazy-import :mod:`apps.core.wikilinks`) and must
stay above the models layer. This module intentionally does not import
:mod:`apps.core.markdown.references`, so including a ``MarkdownField`` on a
model never drags in the reference graph.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import TYPE_CHECKING, NamedTuple

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models.fields import MarkdownField

if TYPE_CHECKING:
    from apps.core.wikilinks import LinkType


def get_markdown_fields(model: type[models.Model]) -> list[str]:
    """Return field names of all MarkdownField instances on a model."""
    return [f.name for f in model._meta.get_fields() if isinstance(f, MarkdownField)]


# ---------------------------------------------------------------------------
# Authoring <-> Storage conversion
# ---------------------------------------------------------------------------


def convert_authoring_to_storage(content: str) -> str:
    """Convert authoring format links to storage format.

    Only affects public-id-based types; ID-based types are already in storage format.

    Raises:
        ValidationError: If any linked target doesn't exist
    """
    if not content:
        return content

    from apps.core.wikilinks import get_enabled_public_id_types, get_patterns

    errors: list[str] = []
    for lt in get_enabled_public_id_types():
        pats = get_patterns(lt)
        content = _convert_to_storage(content, lt, pats["authoring"], errors)

    if errors:
        raise ValidationError(errors)
    return content


def _convert_to_storage(
    content: str,
    lt: LinkType,
    pattern: re.Pattern[str],
    errors: list[str],
) -> str:
    """Convert ``[[type:public_id]]`` to ``[[type:id:N]]`` for one link type."""
    matches = list(pattern.finditer(content))
    if not matches:
        return content

    model = lt.get_model()
    raw_values = [m.group(1) for m in matches]

    if lt.public_id_field is None:
        raise ValueError(f"LinkType '{lt.name}' is not public-id-based")
    by_key: dict[str, models.Model]
    if lt.authoring_lookup:
        by_key = lt.authoring_lookup(model, raw_values)
    else:
        qs = model.objects.filter(**{f"{lt.public_id_field}__in": raw_values})
        by_key = {getattr(obj, lt.public_id_field): obj for obj in qs}

    result = content
    for match in reversed(matches):
        key = match.group(1)
        obj = by_key.get(key)
        if obj:
            result = (
                result[: match.start()]
                + f"[[{lt.name}:id:{obj.pk}]]"
                + result[match.end() :]
            )
        else:
            errors.append(f"{lt.name.title()} not found: [[{lt.name}:{key}]]")
            result = result[: match.start()] + match.group(0) + result[match.end() :]
    return result


class WikilinkRef(NamedTuple):
    """A storage-form wikilink target: a link type plus the row's pk.

    Mirrors :class:`apps.provenance.display.FkRef` — a named key so the
    authoring-lookup map isn't a bare ``tuple[str, int]`` whose positions
    need a comment to read.
    """

    type_name: str
    pk: int


class WikilinkAuthoringLookup:
    """Authoring keys resolved from :class:`WikilinkRef`\\ s.

    Built once per batch by :func:`resolve_wikilink_authoring`; consulted by
    :func:`apply_storage_to_authoring` to rewrite ``[[type:id:N]]`` markers
    without re-querying. Same encapsulated shape as
    :class:`apps.provenance.display.LabelLookup` — the backing dict stays
    private so callers go through ``add``/``get``.
    """

    __slots__ = ("_keys",)

    def __init__(self) -> None:
        self._keys: dict[WikilinkRef, str] = {}

    def add(self, ref: WikilinkRef, key: str) -> None:
        self._keys[ref] = key

    def get(self, ref: WikilinkRef) -> str | None:
        return self._keys.get(ref)


def resolve_wikilink_authoring(texts: Iterable[str]) -> WikilinkAuthoringLookup:
    """Batch-resolve every ``[[type:id:N]]`` marker across ``texts`` to its
    authoring key.

    One query per enabled public-id link type (bounded by the number of link
    types, independent of how many texts are passed), so callers rendering
    many markdown values — edit history, sources — stay query-bounded. Only
    public-id types are resolved; ID-based types are identical in both formats
    and need no conversion.
    """
    from apps.core.wikilinks import get_enabled_public_id_types, get_patterns

    materialized = [t for t in texts if t]
    lookup = WikilinkAuthoringLookup()
    if not materialized:
        return lookup

    for lt in get_enabled_public_id_types():
        # public_id_field is non-None for every type get_enabled_public_id_types yields.
        assert lt.public_id_field is not None
        pattern = get_patterns(lt)["storage"]
        ids: set[int] = set()
        for text in materialized:
            ids.update(int(m.group(1)) for m in pattern.finditer(text))
        if not ids:
            continue
        model = lt.get_model()
        for obj in model.objects.filter(pk__in=ids):
            key = (
                lt.get_authoring_key(obj)
                if lt.get_authoring_key
                else getattr(obj, lt.public_id_field)
            )
            lookup.add(WikilinkRef(lt.name, obj.pk), key)
    return lookup


def apply_storage_to_authoring(text: str, lookup: WikilinkAuthoringLookup) -> str:
    """Rewrite ``[[type:id:N]]`` markers in ``text`` to authoring form using a
    pre-resolved ``lookup`` — no DB access.

    Broken links (target deleted, so absent from ``lookup``) keep storage
    form, matching the editor's behavior.
    """
    if not text:
        return text

    from apps.core.wikilinks import get_enabled_public_id_types, get_patterns

    for lt in get_enabled_public_id_types():
        text = _apply_authoring_one(text, lt, get_patterns(lt)["storage"], lookup)
    return text


def _apply_authoring_one(
    text: str,
    lt: LinkType,
    pattern: re.Pattern[str],
    lookup: WikilinkAuthoringLookup,
) -> str:
    """Rewrite one link type's storage markers using ``lookup``."""
    matches = list(pattern.finditer(text))
    if not matches:
        return text
    result = text
    for match in reversed(matches):
        key = lookup.get(WikilinkRef(lt.name, int(match.group(1))))
        if key is not None:
            result = (
                result[: match.start()] + f"[[{lt.name}:{key}]]" + result[match.end() :]
            )
        # else: keep storage form (target deleted)
    return result


def convert_storage_to_authoring(content: str) -> str:
    """Convert storage format links to authoring format for editing.

    Only affects public-id-based types; ID-based types are the same in both
    formats. Single-text convenience over the batched
    :func:`resolve_wikilink_authoring` / :func:`apply_storage_to_authoring`
    pair, so the editor path and batched callers share one code path.
    """
    if not content:
        return content
    return apply_storage_to_authoring(content, resolve_wikilink_authoring([content]))


def prepare_markdown_claim_value(
    field_name: str, value: object, model_class: type[models.Model]
) -> object:
    """Convert authoring-format links to storage format if the field is a MarkdownField.

    Intended as the single integration point for all write paths (admin,
    API PATCH, ingestion) that store markdown content as claim values.

    Returns the value unchanged if the field is not a MarkdownField or
    the value is not a non-empty string.

    Raises :exc:`~django.core.exceptions.ValidationError` if any linked
    targets don't exist.
    """
    if (
        isinstance(value, str)
        and value
        and field_name in get_markdown_fields(model_class)
    ):
        return convert_authoring_to_storage(value)
    return value
