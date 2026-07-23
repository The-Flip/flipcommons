"""Repair the ``claim_key`` rows catalog ``0026`` left stale, then make the
drift impossible.

``claim_key`` is a materialized ``make_claim_key(field_name, ...)`` — for a
scalar claim it *is* ``field_name``; for a relationship claim it is
``field_name`` joined to sorted identity parts by ``|``. Either way
``field_name`` is an input to it, so rewriting one without recomputing the
other leaves a row advertising a slot nothing can derive.

Catalog ``0026`` promoted ``extra_data['ipdb.model_number']`` to the
``manufacturer_model_identifier`` column and renamed ``field_name`` on the
claims. It did not touch ``claim_key``. The resulting rows say they are about
``manufacturer_model_identifier`` while competing in a slot called
``ipdb.model_number`` — a slot no post-promotion claim can ever land in,
because the write path derives the key from the field name. Rival values for
one column therefore stop competing: each sits alone in its own slot and both
render as winners on the Sources page and in Edit History.

Nothing rejected it. Resolution reads ``field_name``, so the materialized
column was always correct and the fault stayed invisible until the Sources page
started grouping by slot. The canonicality check in ``validation`` (rule 8)
runs only inside ``validate_single_relationship_claim``, and ``0026`` used
``apps.get_model`` with a raw ``.update()``, which skips model validation
entirely. That is the case for putting the invariant in the database: a
constraint is the only layer a migration cannot walk past.

When this was written, every affected row was active, carried the IPDB ingest
actor, and collided with nothing. None of that is assumed: the collision check
and the residue sweep below re-derive it against whatever database this runs
on, because a collision means two rival claims from one actor and choosing a
survivor is not a migration's call.
"""

from __future__ import annotations

from django.db import migrations, models
from django.db.models import F, Q, Value
from django.db.models.functions import Concat, Left, Length
from django.db.models.lookups import Exact

# The pre-promotion extra_data key, still sitting in claim_key on the bad rows.
_STALE_CLAIM_KEY = "ipdb.model_number"
# The post-promotion field name, already written to field_name by catalog 0026.
_FIELD_NAME = "manufacturer_model_identifier"
# Mirrors CLAIM_KEY_SEPARATOR; migrations must not import from app code, since
# the app is free to change while this migration's meaning is frozen.
_SEPARATOR = "|"


def _derivable_key() -> Q:
    """claim_key is still computable from field_name.

    Either the key IS the field name (scalar claims, where ``make_claim_key``
    returns its input unchanged), or it is the field name followed by the
    separator (relationship claims, where identity parts are appended).

    One spelling, used twice: as the CHECK constraint's condition below, and as
    the sweep that names offending rows *before* the constraint exists to reject
    them. Writing it out twice is what put us here in the first place.

    Left/Length rather than ``__startswith`` because the latter compiles to
    LIKE, where the ``_`` in field names like ``short_name`` is a
    single-character wildcard and would quietly widen the check.
    """
    return Q(claim_key=F("field_name")) | Q(
        Exact(
            Left("claim_key", Length("field_name") + Value(1)),
            Concat("field_name", Value(_SEPARATOR)),
        )
    )


def repair_claim_keys(apps, schema_editor):
    Claim = apps.get_model("provenance", "Claim")

    stale = Claim.objects.filter(field_name=_FIELD_NAME, claim_key=_STALE_CLAIM_KEY)

    # The unique index (content_type, object_id, actor, claim_key) is partial on
    # is_active, so only active rows can collide. A collision would mean this
    # actor asserted the same field both before and after the promotion, and
    # picking a survivor is a judgement call — abort and let a human make it.
    moving = list(
        stale.filter(is_active=True).values_list(
            "pk", "content_type_id", "object_id", "actor_id"
        )
    )
    occupied = set(
        Claim.objects.filter(claim_key=_FIELD_NAME, is_active=True).values_list(
            "content_type_id", "object_id", "actor_id"
        )
    )
    blocked = sorted(
        pk for pk, ct, obj, actor in moving if (ct, obj, actor) in occupied
    )
    if blocked:
        raise RuntimeError(
            f"Repairing {len(blocked)} claim_key(s) would collide with an "
            f"existing active claim on the same (subject, actor). Claim pks: "
            f"{blocked}. Resolve by hand — deciding which rival value wins is "
            f"not this migration's call."
        )

    stale.update(claim_key=F("field_name"))

    # Catch anything drifted by a cause this migration doesn't know about,
    # before AddConstraint fails on it with a message that names no rows.
    if residue := list(
        Claim.objects.exclude(_derivable_key()).values_list(
            "pk", "field_name", "claim_key"
        )[:20]
    ):
        raise RuntimeError(
            "claim_key is not derivable from field_name on rows this migration "
            f"does not target (showing up to 20): {residue}. The constraint "
            "cannot be added until they are repaired too."
        )


def unrepair_claim_keys(apps, schema_editor):
    """No-op, deliberately.

    The pre-repair state is the corrupt one, and reconstructing it would violate
    the constraint this migration adds. It also isn't needed: catalog ``0026``'s
    reverse puts *both* ``field_name`` and ``claim_key`` back on
    ``ipdb.model_number``, so unwinding past this point lands on a consistent
    pre-promotion state regardless of what happens here.
    """


class Migration(migrations.Migration):
    dependencies = [
        ("actors", "0002_alter_actor_priority_help_text"),
        ("citation", "0022_alter_citationinstance_quote"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("core", "0001_initial"),
        ("provenance", "0026_fk_claim_values_to_pk"),
        # The repair must run after the migration whose rows it repairs. Django
        # happens to pick that order today without being told, but incidentally
        # — reordered, this migration silently no-ops and the constraint lands
        # before the promotion. That is survivable only while catalog 0026
        # rewrites both columns in one statement, so leaving it implicit would
        # make this migration's correctness depend on that one staying correct,
        # which is the coupling that caused the bug in the first place.
        # Provenance→catalog edges are established here (see 0007, 0026).
        ("catalog", "0026_promote_manufacturer_model_identifier"),
    ]

    operations = [
        migrations.RunPython(repair_claim_keys, unrepair_claim_keys),
        migrations.AddConstraint(
            model_name="claim",
            constraint=models.CheckConstraint(
                condition=_derivable_key(),
                name="provenance_claim_key_derived_from_field_name",
                violation_error_code="cross_field",
                violation_error_message=(
                    "claim_key must equal field_name, or begin with "
                    f"field_name + {_SEPARATOR!r} for relationship claims."
                ),
            ),
        ),
    ]
