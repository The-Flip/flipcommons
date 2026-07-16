"""Transform legacy lineage-FK claims into model_relationship edge claims.

The ``converted_from`` / ``bootleg_of`` / ``licensed_build_of`` scalar-FK
claims predate the ModelRelationship edge table
(docs/plans/catalog_data_model/ModelRelationships.md). The seed ingest wrote
``converted_from`` claims long before the patch campaign, so prod carries rows
no patch rework will ever touch — they must be migrated in place.

Each old claim row is **rewritten**, not replaced: field_name/claim_key/value
become the edge-claim shape while the row keeps its pk, so attribution,
changeset linkage and attached citations ride along untouched. Active and
inactive claims alike are transformed (inactive rows are history; revert can
reactivate them, so leaving them in the old vocabulary would poison undo).

The value mapping is the mechanical one the plan doc prescribes:

- ``converted_from`` → (conversion, unknown) — or (conversion_kit, unknown)
  when the subject carries the ``conversion-kit`` tag, which is what that tag
  meant alongside the FK.
- ``bootleg_of`` → (copy, unlicensed); ``licensed_build_of`` → (copy,
  licensed). Zero such rows shipped to prod (the fields and the patches using
  them all postdate the prod freeze at 0038), so on prod these arms are no-ops;
  on dev DBs mid-campaign they preserve history until the reworked patches
  supersede it.

Collision rule: the patch campaign asserts edge claims from the **same actor**
(flipcommons-catalog) as the legacy claims. Where an active edge claim with
the same (subject, actor, claim_key) already exists, the legacy claim is
transformed but **deactivated** — the reworked patch's per-row-sourced values
win, and the one-active-claim-per-(actor, claim_key) constraint holds. The
same rule serializes two legacy claims mapping to one edge identity (e.g.
``bootleg_of`` and ``converted_from`` naming the same target).

After the claim rewrite, missing ModelRelationship rows are materialized
directly (the resolver isn't callable from a migration) and the legacy FK
columns are nulled so no stale denormalized value outlives its claims. The
columns themselves are dropped in a later migration, after the patch campaign
finishes and the dual-read consumers collapse to edges-only.
"""

from __future__ import annotations

from django.db import migrations

_LEGACY_FIELDS = ("converted_from", "bootleg_of", "licensed_build_of")

# (relationship_type, license_status) per legacy field; converted_from's type
# is decided per-subject by the conversion-kit tag.
_COPY_PAYLOADS = {
    "bootleg_of": ("copy", "unlicensed"),
    "licensed_build_of": ("copy", "licensed"),
}


def _edge_claim_key(target_pk: int) -> str:
    """The canonical model_relationship claim_key for a machine target.

    Inlined rather than imported from ``make_claim_key`` (migrations must not
    depend on live app code): the identity is ``target_machine`` alone — the
    label is a non-identity member and never enters the key — and an int pk
    needs no percent-escaping. Locked against the live builder by the
    migration's test.
    """
    return f"model_relationship|target_machine:{target_pk}"


def transform_lineage_claims(apps, schema_editor):
    Claim = apps.get_model("provenance", "Claim")
    ContentType = apps.get_model("contenttypes", "ContentType")
    MachineModel = apps.get_model("catalog", "MachineModel")
    MachineModelTag = apps.get_model("catalog", "MachineModelTag")
    ModelRelationship = apps.get_model("catalog", "ModelRelationship")
    Tag = apps.get_model("catalog", "Tag")

    ct = ContentType.objects.filter(app_label="catalog", model="machinemodel").first()
    if ct is None:
        return  # fresh DB: nothing seeded, nothing to transform

    kit_tag = Tag.objects.filter(slug="conversion-kit").first()
    kit_subjects: set[int] = (
        set(
            MachineModelTag.objects.filter(tag=kit_tag).values_list(
                "machinemodel_id", flat=True
            )
        )
        if kit_tag
        else set()
    )
    machine_pks = set(MachineModel.objects.values_list("pk", flat=True))
    active_edge_keys = set(
        Claim.objects.filter(
            content_type=ct, field_name="model_relationship", is_active=True
        ).values_list("object_id", "actor_id", "claim_key")
    )

    transformed_active: list = []
    for field_name in _LEGACY_FIELDS:
        claims = Claim.objects.filter(content_type=ct, field_name=field_name).order_by(
            "pk"
        )
        for claim in claims.iterator():
            target_pk = claim.value
            if not isinstance(target_pk, int) or isinstance(target_pk, bool):
                # A cleared-FK assertion (None/""): edges express absence by
                # absence, so there is nothing to transform it into. Deactivate
                # so the claim can't outlive its field.
                if claim.is_active:
                    claim.is_active = False
                    claim.save(update_fields=["is_active"])
                continue
            if field_name == "converted_from":
                rel_type = (
                    "conversion_kit"
                    if claim.object_id in kit_subjects
                    else "conversion"
                )
                payload = (rel_type, "unknown")
            else:
                payload = _COPY_PAYLOADS[field_name]
            claim_key = _edge_claim_key(target_pk)
            edge_key = (claim.object_id, claim.actor_id, claim_key)
            stays_active = (
                claim.is_active
                and edge_key not in active_edge_keys
                # A dangling or self-referential target can't materialize; keep
                # the history but never as the actor's active assertion.
                and target_pk in machine_pks
                and target_pk != claim.object_id
            )
            claim.field_name = "model_relationship"
            claim.claim_key = claim_key
            claim.value = {
                "target_machine": target_pk,
                "target_label": "",
                "relationship_type": payload[0],
                "license_status": payload[1],
                "exists": True,
            }
            claim.is_active = stays_active
            claim.save(update_fields=["field_name", "claim_key", "value", "is_active"])
            if stays_active:
                active_edge_keys.add(edge_key)
                transformed_active.append(claim)

    # Materialize rows for the claims that stayed active. Only the rungs this
    # migration creates are checked — campaign-authored claims were already
    # materialized by the resolver.
    for claim in transformed_active:
        target_pk = claim.value["target_machine"]
        exists = ModelRelationship.objects.filter(
            machine_model_id=claim.object_id, target_machine_id=target_pk
        ).exists()
        if not exists:
            ModelRelationship.objects.create(
                machine_model_id=claim.object_id,
                target_machine_id=target_pk,
                target_label="",
                relationship_type=claim.value["relationship_type"],
                license_status=claim.value["license_status"],
            )

    # No claim backs the legacy columns any more; null them so no stale
    # denormalized value survives (the columns drop in a later migration).
    MachineModel.objects.filter(converted_from__isnull=False).update(
        converted_from=None
    )
    MachineModel.objects.filter(bootleg_of__isnull=False).update(bootleg_of=None)
    MachineModel.objects.filter(licensed_build_of__isnull=False).update(
        licensed_build_of=None
    )


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0020_modelrelationship"),
        ("provenance", "0026_fk_claim_values_to_pk"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(
            transform_lineage_claims, migrations.RunPython.noop, elidable=False
        ),
    ]
