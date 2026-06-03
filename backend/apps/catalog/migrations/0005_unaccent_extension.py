"""Enable the Postgres ``unaccent`` extension for diacritic-insensitive title
search (``LOWER(UNACCENT(name))`` in the ``q`` filter).

``UnaccentExtension`` is a no-op on non-PostgreSQL backends, so this is safe on
the SQLite dev/CI database — where title-name search falls back to plain
case-insensitive ``icontains`` (no diacritic folding) by design.
"""

from django.contrib.postgres.operations import UnaccentExtension
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        (
            "catalog",
            "0004_remove_machinemodel_catalog_machinemodel_pinside_id_min_and_more",
        ),
    ]

    operations = [
        UnaccentExtension(),
    ]
