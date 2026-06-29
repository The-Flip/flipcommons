"""The parent-promotion migration is state-only (zero DDL) but changes state.

Migration ``0016`` promotes ``Theme.parents`` / ``GameplayFeature.parents`` to
the explicit ``ThemeParent`` / ``GameplayFeatureParent`` through-models, which
are pinned to the existing auto-M2M tables. That makes it a
``SeparateDatabaseAndState`` with empty ``database_operations`` — no DDL runs.

This test pins both halves: ``database_operations == []`` (the zero-DDL
guarantee) **and** that the four state operations are present (so the migration
still actually teaches Django's state the explicit models — an empty migration
would pass the first assertion alone).
"""

from __future__ import annotations

import importlib

from django.db import migrations

MIGRATION = "apps.catalog.migrations.0016_promote_parent_through_models"


def test_parent_promotion_is_state_only_but_changes_state() -> None:
    operations = importlib.import_module(MIGRATION).Migration.operations

    assert len(operations) == 1
    op = operations[0]
    assert isinstance(op, migrations.SeparateDatabaseAndState)

    # Zero-DDL guarantee.
    assert op.database_operations == []

    # ...but the state genuinely changes: two CreateModels + two AlterFields.
    creates = {
        o.name for o in op.state_operations if isinstance(o, migrations.CreateModel)
    }
    alters = {
        (o.model_name, o.name)
        for o in op.state_operations
        if isinstance(o, migrations.AlterField)
    }
    assert creates == {"GameplayFeatureParent", "ThemeParent"}
    assert alters == {("gameplayfeature", "parents"), ("theme", "parents")}
    assert len(op.state_operations) == 4
