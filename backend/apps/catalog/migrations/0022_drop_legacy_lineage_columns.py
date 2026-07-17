"""Drop the legacy lineage FK columns after a final claim sweep.

``bootleg_of``, ``licensed_build_of`` and ``converted_from`` are fully
replaced by ``ModelRelationship`` edges (see
docs/plans/catalog_data_model/ModelRelationships.md, step 9). ``0021``
transformed every legacy-FK claim in place when it ran; the sweep re-runs
here so any legacy claim authored *between* the two migrations (possible on
a long-lived dev DB; on prod, both apply in one deploy) is transformed
rather than silently orphaned by the column drop.

Deploy-window caveat, accepted deliberately: while this migration runs, the
*old* release may still serve traffic, and its editor accepts legacy-FK
claims — a claim committed after the sweep's read but before cutover would
be missed and left as an inert orphan (it classifies as EXTRA post-drop; the
user's input survives as a claim, nothing is lost silently at the DB). The
window is seconds wide, requires a legacy-FK edit in exactly that moment,
and this deploy is operator-initiated at a quiet time, so we take the
single-deployment path rather than an expand/contract release pair.
Post-deploy check (should return 0):

    Claim.objects.filter(
        field_name__in=["bootleg_of", "licensed_build_of", "converted_from"]
    ).count()
"""

from importlib import import_module

from django.db import migrations

# A module name starting with a digit can't be imported with import syntax.
_lineage = import_module("apps.catalog.migrations.0021_lineage_fk_claims_to_edges")
transform_lineage_claims = _lineage.transform_lineage_claims


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0021_lineage_fk_claims_to_edges"),
    ]

    operations = [
        migrations.RunPython(
            transform_lineage_claims, migrations.RunPython.noop, elidable=False
        ),
        migrations.RemoveConstraint(
            model_name="machinemodel",
            name="catalog_machinemodel_converted_from_not_self",
        ),
        migrations.RemoveConstraint(
            model_name="machinemodel",
            name="catalog_machinemodel_bootleg_of_not_self",
        ),
        migrations.RemoveConstraint(
            model_name="machinemodel",
            name="catalog_machinemodel_licensed_build_of_not_self",
        ),
        migrations.RemoveField(
            model_name="machinemodel",
            name="bootleg_of",
        ),
        migrations.RemoveField(
            model_name="machinemodel",
            name="converted_from",
        ),
        migrations.RemoveField(
            model_name="machinemodel",
            name="licensed_build_of",
        ),
    ]
