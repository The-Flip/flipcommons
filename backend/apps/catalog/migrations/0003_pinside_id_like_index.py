"""Create the ``varchar_pattern_ops`` index Django implies for the unique
``MachineModel.pinside_id`` on databases that predate ``0001``.

On PostgreSQL, ``CreateModel`` emits a ``<column>_like`` btree index beside every
unique or indexed varchar column, so a database built from ``0001`` has it. The
production database was not built from ``0001``: its ``pinside_id`` became a
varchar through an earlier type-altering migration that never added the index,
and it records ``0001`` as applied without running it. This closes that one gap
so the migration state and the live schema agree. ``IF NOT EXISTS`` makes it a
no-op where ``0001`` already ran; other backends have no such index and skip it.
"""

from django.db import migrations


def _create_like_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        "CREATE INDEX IF NOT EXISTS catalog_machinemodel_pinside_id_0a315f1d_like "
        "ON catalog_machinemodel (pinside_id varchar_pattern_ops)"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0002_unaccent_extension"),
    ]

    operations = [
        migrations.RunPython(_create_like_index, migrations.RunPython.noop),
    ]
