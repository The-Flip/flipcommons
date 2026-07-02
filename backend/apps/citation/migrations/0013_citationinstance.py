# CitationInstance relocates from the provenance app to the citation app.
#
# The table already exists (built by provenance migrations; ``db_table`` keeps
# the historical ``provenance_citationinstance`` name), so the CreateModel is
# wrapped in SeparateDatabaseAndState — state only, no SQL. The paired
# provenance migration retargets its references and deletes the old state
# entry.
#
# The one real database operation is the ContentType rename: a ContentType's
# identity is ``(app_label, model)``, so the existing row is renamed IN PLACE
# (provenance → citation). Letting Django mint a fresh row instead would leave
# every inline ``[[cite:...]]`` wikilink's ``RecordReference.target_type``
# pointing at the orphaned old row, splitting the "what links here" reference
# graph.

import apps.core.validators
import django.db.models.deletion
import django.db.models.functions.datetime
from django.db import migrations, models


def _adopt_contenttype(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    ContentType.objects.filter(app_label="provenance", model="citationinstance").update(
        app_label="citation"
    )
    _clear_contenttype_cache()


def _return_contenttype(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    ContentType.objects.filter(app_label="citation", model="citationinstance").update(
        app_label="provenance"
    )
    _clear_contenttype_cache()


def _clear_contenttype_cache():
    # The historical model's plain manager has no cache; the live
    # ContentTypeManager does, and a stale entry would resurrect the old
    # identity within this process.
    from django.contrib.contenttypes.models import ContentType

    ContentType.objects.clear_cache()


class Migration(migrations.Migration):

    dependencies = [
        ("citation", "0012_tighten_attribution_not_null"),
        ("contenttypes", "0002_remove_content_type_name"),
        # After the legacy claim-FK drop, so the adopted state matches the
        # table's final shape.
        ("provenance", "0020_remove_citationinstance_prov_citinst_claim_idx_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="CitationInstance",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        ("slug", models.CharField(max_length=8, unique=True)),
                        (
                            "locator",
                            models.CharField(
                                blank=True,
                                db_default="",
                                default="",
                                max_length=200,
                                validators=[
                                    apps.core.validators.validate_no_mojibake
                                ],
                            ),
                        ),
                        (
                            "created_at",
                            models.DateTimeField(
                                auto_now_add=True,
                                db_default=django.db.models.functions.datetime.Now(),
                            ),
                        ),
                        (
                            "citation_source",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="instances",
                                to="citation.citationsource",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "provenance_citationinstance",
                        "indexes": [
                            models.Index(
                                fields=["citation_source"],
                                name="prov_citinst_source_idx",
                            )
                        ],
                        "constraints": [
                            models.CheckConstraint(
                                condition=models.Q(("slug__length", 8)),
                                name="prov_citinst_slug_length",
                            )
                        ],
                    },
                ),
            ],
        ),
        migrations.RunPython(_adopt_contenttype, _return_contenttype),
    ]
