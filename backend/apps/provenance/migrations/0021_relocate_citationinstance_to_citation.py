# The provenance half of CitationInstance's relocation to the citation app:
# retarget the join FK and the Claim M2M at citation.CitationInstance, then
# delete the old state entry. Everything is state-only — the paired citation
# migration (0013) adopted the model over the existing, unrenamed table, so
# there is no schema to change here. Its index and CHECK constraint live on
# unchanged in the database; the RemoveIndex/RemoveConstraint below only
# release them from provenance's model state (citation's state re-declares
# them under the same names).

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("citation", "0013_citationinstance"),
        ("provenance", "0020_remove_citationinstance_prov_citinst_claim_idx_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RemoveIndex(
                    model_name="citationinstance",
                    name="prov_citinst_source_idx",
                ),
                migrations.RemoveConstraint(
                    model_name="citationinstance",
                    name="prov_citinst_slug_length",
                ),
                migrations.AlterField(
                    model_name="claimcitationinstance",
                    name="citation_instance",
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="claim_links",
                        to="citation.citationinstance",
                    ),
                ),
                migrations.AlterField(
                    model_name="claim",
                    name="citation_instances",
                    field=models.ManyToManyField(
                        related_name="claims",
                        through="provenance.ClaimCitationInstance",
                        to="citation.citationinstance",
                    ),
                ),
                migrations.DeleteModel(
                    name="CitationInstance",
                ),
            ],
        ),
    ]
