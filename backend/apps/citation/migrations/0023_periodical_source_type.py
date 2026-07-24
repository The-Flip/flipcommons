# The magazine → periodical rename. IPDB's print references turned out to
# span newspapers, trade journals, newsletters and house organs, not just
# magazines — and none of them differ in behavior, so the type is renamed
# rather than split (see docs/Citations.md).
#
# The RunPython sits between the constraint swap on purpose: forward, rows
# rename after the old magazine-only CHECK drops and before the new one
# lands; unapplied, Django reverses the order, so rows rename back before
# the old CHECK returns. Both directions matter — prod carries seeded
# magazine rows, and the migration tests rewind below this point.

from django.db import migrations, models

_OLD = "magazine"
_NEW = "periodical"


def rename_forward(apps, schema_editor):
    CitationSource = apps.get_model("citation", "CitationSource")
    CitationSource.objects.filter(source_type=_OLD).update(source_type=_NEW)


def rename_reverse(apps, schema_editor):
    CitationSource = apps.get_model("citation", "CitationSource")
    CitationSource.objects.filter(source_type=_NEW).update(source_type=_OLD)


class Migration(migrations.Migration):

    dependencies = [
        ("citation", "0022_alter_citationinstance_quote"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="citationsource",
            name="citation_citationsource_source_type_valid",
        ),
        migrations.RunPython(rename_forward, rename_reverse),
        migrations.AlterField(
            model_name="citationsource",
            name="source_type",
            field=models.CharField(
                choices=[
                    ("book", "Book"),
                    ("periodical", "Periodical"),
                    ("web", "Web"),
                    ("video", "Video"),
                ],
                max_length=20,
            ),
        ),
        migrations.AddConstraint(
            model_name="citationsource",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("source_type__in", ["book", "periodical", "web", "video"])
                ),
                name="citation_citationsource_source_type_valid",
            ),
        ),
    ]
