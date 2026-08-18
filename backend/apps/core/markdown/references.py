"""The markdown → :class:`~apps.core.models.RecordReference` bridge.

Parses wikilinks from saved markdown content and writes
``RecordReference`` rows. Save-path callers import directly from here so
the dependency on the reference graph is visible in their imports.

Future non-markdown populators (citation-note text, YAML/JSON-stored
references) will write their own bridges in their own packages.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from django.db import models, transaction
from django.db.models import Q

from apps.core.markdown.field import convert_authoring_to_storage
from apps.core.models import RecordReference
from apps.core.wikilinks import get_enabled_link_types, get_patterns


def sync_references(source: models.Model) -> None:
    """Sync the RecordReference rows for every markdown field on *source*.

    Compares the links across all of the instance's ``MarkdownField`` content
    against its existing rows, then batch-creates/deletes the diff. Reads the
    fields off the instance, so an unsaved edit must be assigned first.

    Reconciliation is per SOURCE and cannot be narrowed: a row is keyed
    ``(source_type, source_id, target_type, target_id)`` and carries no field
    identity, so anything less than the full content reads the other fields'
    links as stale and deletes them.
    """
    from django.contrib.contenttypes.models import ContentType

    from apps.core.markdown.field import get_markdown_fields

    content = "\n".join(
        getattr(source, name, "") or "" for name in get_markdown_fields(type(source))
    )

    # Parse all link IDs from content using registered patterns
    links_by_model: dict[type[Any], set[int]] = {}
    for lt in get_enabled_link_types():
        pats = get_patterns(lt)
        pattern = pats.get("storage") or pats.get("id")
        if pattern is None:
            continue
        ids = {int(m.group(1)) for m in pattern.finditer(content)}
        links_by_model[lt.get_model()] = ids

    if not links_by_model:
        return

    # Pre-compute all ContentTypes (single query via get_for_models)
    source_ct = ContentType.objects.get_for_model(source)
    content_types = ContentType.objects.get_for_models(*links_by_model.keys())

    # Get existing references for this source
    existing_refs = RecordReference.objects.filter(
        source_type=source_ct, source_id=source.pk
    ).values_list("target_type_id", "target_id")
    existing_by_ct: dict[int, set[int]] = {}
    for ct_id, target_id in existing_refs:
        existing_by_ct.setdefault(ct_id, set()).add(target_id)

    to_create: list[RecordReference] = []
    to_delete_filters: list[Q] = []

    for model_class, target_ids in links_by_model.items():
        target_ct = content_types[model_class]
        existing_ids = existing_by_ct.get(target_ct.id, set())

        if not target_ids:
            # No links of this type — clean up any stale references
            if existing_ids:
                to_delete_filters.append(
                    Q(target_type=target_ct, target_id__in=existing_ids)
                )
            continue

        # Only reference targets that actually exist
        valid_ids = set(
            model_class.objects.filter(pk__in=target_ids).values_list("pk", flat=True)
        )

        # Refs to add
        for target_id in valid_ids - existing_ids:
            to_create.append(
                RecordReference(
                    source_type=source_ct,
                    source_id=source.pk,
                    target_type=target_ct,
                    target_id=target_id,
                )
            )

        # Refs to remove
        ids_to_remove = existing_ids - target_ids
        if ids_to_remove:
            to_delete_filters.append(
                Q(target_type=target_ct, target_id__in=ids_to_remove)
            )

    # Batch operations
    if to_delete_filters:
        delete_q = to_delete_filters[0]
        for q in to_delete_filters[1:]:
            delete_q |= q
        RecordReference.objects.filter(
            source_type=source_ct, source_id=source.pk
        ).filter(delete_q).delete()

    if to_create:
        RecordReference.objects.bulk_create(to_create, ignore_conflicts=True)


def save_inline_markdown_field(
    instance: models.Model,
    field: str,
    raw_text: str,
    *,
    extra_update_fields: Sequence[str] = (),
) -> None:
    """Convert, save, and sync a markdown text field from an inline AJAX edit.

    Converts authoring-format links to storage format, saves the field,
    and syncs the :class:`~apps.core.models.RecordReference` table.

    Args:
        extra_update_fields: Additional field names to include in
            ``save(update_fields=...)``, e.g. ``["updated_by"]``.

    Raises :exc:`~django.core.exceptions.ValidationError` if any linked
    targets don't exist.
    """
    text = convert_authoring_to_storage(raw_text) if raw_text else raw_text
    with transaction.atomic():
        setattr(instance, field, text)
        instance.save(update_fields=[field, "updated_at", *extra_update_fields])
        sync_references(instance)
