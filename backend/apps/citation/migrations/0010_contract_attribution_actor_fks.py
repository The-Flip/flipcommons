"""Contract: drop the legacy User columns and rename the Actor columns into place.

Per model, in order: remove the old ``created_by``/``updated_by`` (FK to User),
then rename ``created_by_actor``/``updated_by_actor`` to ``created_by`` /
``updated_by`` (the remove must precede the rename so the target name is free).
The end state — ``created_by``/``updated_by`` as nullable ``PROTECT`` FKs to
``actors.Actor`` — is exactly what ``ActorAttributedModel`` declares, so
``makemigrations --check`` reports no drift after this migration.
"""

from __future__ import annotations

from django.db import migrations

_MODELS = ["citationsource", "citationsourcelink", "citationsourcerootdomain"]


def _contract(model_name: str) -> list[migrations.operations.base.Operation]:
    return [
        migrations.RemoveField(model_name=model_name, name="created_by"),
        migrations.RemoveField(model_name=model_name, name="updated_by"),
        migrations.RenameField(
            model_name=model_name,
            old_name="created_by_actor",
            new_name="created_by",
        ),
        migrations.RenameField(
            model_name=model_name,
            old_name="updated_by_actor",
            new_name="updated_by",
        ),
    ]


class Migration(migrations.Migration):
    dependencies = [
        ("citation", "0009_backfill_attribution_actor_fks"),
    ]

    operations = [op for model_name in _MODELS for op in _contract(model_name)]
