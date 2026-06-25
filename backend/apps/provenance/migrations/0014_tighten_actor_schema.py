"""Tighten the actor schema once the backfill (0013) has filled every row.

``Actor`` is the single attribution target (docs/plans/auth/Actors.md). With the
historical tail backfilled and every consumer reading ``actor``, the schema can
finally match runtime reality. Validation-only — no data moves:

- ``ChangeSet.actor`` / ``Claim.actor`` / ``Claim.changeset`` become NOT NULL
  (0013 left no NULLs, so the scans pass).
- A unified partial-unique index ``provenance_unique_active_claim_per_actor`` on
  ``(content_type, object_id, actor, claim_key) WHERE is_active`` — the union of
  the legacy per-user/per-source indexes (different actors are different keys, so
  it is never stricter). Safe to build: 0013 preserved one-active-claim-per-author
  and actor maps 1:1 to its backing record.
- Actor-led read indexes: ``(actor, content_type, object_id)`` on Claim (profile
  contributions) and ``provenance_cs_actor_{created,action}`` on ChangeSet (revert
  experience gate + profile edit count).

The claim-mint dedupe flips to the ``actor`` key in the same PR (claim_writer).
The legacy ``user``/``source`` columns, their indexes and CHECKs stay until "Drop
dead stuff"; this migration only adds. Holds a brief ACCESS EXCLUSIVE lock during
the NOT NULL/index DDL — run it in the deploy window.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('actors', '0001_initial'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('core', '0001_initial'),
        ('provenance', '0013_backfill_actor_fks'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='changeset',
            name='actor',
            field=models.ForeignKey(help_text='The actor this changeset is attributed to.', on_delete=django.db.models.deletion.PROTECT, related_name='changesets', to='actors.actor'),
        ),
        migrations.AlterField(
            model_name='claim',
            name='actor',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='claims', to='actors.actor'),
        ),
        migrations.AlterField(
            model_name='claim',
            name='changeset',
            field=models.ForeignKey(help_text='The edit session that wrote this claim; carries its attribution.', on_delete=django.db.models.deletion.PROTECT, related_name='claims', to='provenance.changeset'),
        ),
        migrations.AddIndex(
            model_name='changeset',
            index=models.Index(fields=['actor', '-created_at'], name='provenance_cs_actor_created'),
        ),
        migrations.AddIndex(
            model_name='changeset',
            index=models.Index(fields=['actor', 'action', '-created_at'], name='provenance_cs_actor_action'),
        ),
        migrations.AddIndex(
            model_name='claim',
            index=models.Index(fields=['actor', 'content_type', 'object_id'], name='provenance__actor_i_08a433_idx'),
        ),
        migrations.AddConstraint(
            model_name='claim',
            constraint=models.UniqueConstraint(condition=models.Q(('is_active', True)), fields=('content_type', 'object_id', 'actor', 'claim_key'), name='provenance_unique_active_claim_per_actor'),
        ),
    ]
