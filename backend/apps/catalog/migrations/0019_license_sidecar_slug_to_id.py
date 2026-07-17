"""Convert image-attribution sidecars from ``__license_slug`` to ``__license_id``.

Image-field resolution denormalizes the winning claim's effective license into
``extra_data`` beside the image value. The sidecar used to store the License
*slug*, which went stale on a License rename; it now stores the License PK
and the read API resolves id→slug at read time. The stamp only refreshes when
an entity re-resolves, so without this migration every already-materialized
row would keep the old key and the reader (which knows only ``__license_id``)
would silently drop attribution until an entity-by-entity re-resolve.

Scans every model carrying an ``extra_data`` JSONField (introspected, not
hand-listed), rewrites ``{field}.__license_slug`` → ``{field}.__license_id``
via the License table, and drops the old key. A slug naming no License fails
the whole migration (atomic) — licenses are near-static reference data, so an
unresolvable slug means something a human should look at, and letting it
through would silently drop that row's attribution anyway.
"""

from __future__ import annotations

from django.core.exceptions import FieldDoesNotExist
from django.db import migrations, models

_SLUG_SUFFIX = ".__license_slug"
_ID_SUFFIX = ".__license_id"
_BATCH_SIZE = 1000


def _extra_data_models(apps):
    for model in apps.get_models():
        try:
            field = model._meta.get_field("extra_data")
        except FieldDoesNotExist:
            continue
        if isinstance(field, models.JSONField):
            yield model


def convert_license_sidecars(apps, schema_editor):
    License = apps.get_model("core", "License")
    pk_by_slug = dict(License.objects.values_list("slug", "pk"))

    # Two phases — mutate in memory across every model first, write only if
    # nothing failed — so no row is touched when the migration is going to
    # raise (belt to the migration transaction; keeps direct callers safe too).
    failures: list[str] = []
    changed_by_model: list[tuple[object, list]] = []
    for model in _extra_data_models(apps):
        changed = []
        for obj in model.objects.exclude(extra_data={}).exclude(
            extra_data__isnull=True
        ):
            extra = obj.extra_data
            if not isinstance(extra, dict):
                continue
            slug_keys = [k for k in extra if k.endswith(_SLUG_SUFFIX)]
            if not slug_keys:
                continue
            for key in slug_keys:
                base = key[: -len(_SLUG_SUFFIX)]
                slug = extra.pop(key)
                if slug is None:
                    extra[f"{base}{_ID_SUFFIX}"] = None
                elif slug in pk_by_slug:
                    extra[f"{base}{_ID_SUFFIX}"] = pk_by_slug[slug]
                else:
                    failures.append(
                        f"{model._meta.label} pk={obj.pk}: {key}={slug!r} "
                        f"names no License"
                    )
            changed.append(obj)
        if changed:
            changed_by_model.append((model, changed))

    if failures:
        report = "\n  ".join(failures)
        raise RuntimeError(
            f"Cannot convert {len(failures)} license sidecar(s) — fix the "
            f"License slugs or the stored sidecars before migrating:\n  {report}"
        )

    for model, changed in changed_by_model:
        model.objects.bulk_update(changed, ["extra_data"], batch_size=_BATCH_SIZE)


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0018_machinemodel_licensed_build_of_and_more"),
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(convert_license_sidecars, migrations.RunPython.noop),
    ]
