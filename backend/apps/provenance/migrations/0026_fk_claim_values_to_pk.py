"""Convert scalar FK claim values from public_id strings to target PKs.

FK claim values historically stored the target's slug (``location_path`` for
``Location.parent``), which rotted when the target was renamed: resolution
silently NULLed nullable FKs and raised IntegrityError on NOT NULL ones. The
claim layer now stores the target's integer PK — this migration converts every
existing FK claim, **active and retracted alike** (retracted claims are
reactivated by revert, so leaving them in slug form would poison undo).

Resolution strategy, per value (all string matching on the trimmed form —
the old write path stored authored values verbatim, so padded strings and
YAML-numeric slugs stored as ints both previously resolved):

1. ``None``/``""`` are the clear sentinels → skip; whitespace-only strings
   (a clear on the old normalize-at-lookup path) canonicalize to ``""``. An
   ``int`` is normally an already-converted PK (idempotent re-run) → skip —
   unless its str form matches a target slug (current, or former via slug
   history) for a *different* row, in which case it's a legacy YAML-numeric
   slug (converted) or, if it's simultaneously a live PK, an ambiguity a
   human must resolve (fail).
2. Look the string up in the target table by its public-id column (frozen in
   ``LOOKUP_OVERRIDES`` below — historical models carry no ClassVars).
3. Still unresolved → slug-claim history: ``slug`` is itself a claimed field,
   so a renamed target's former slugs survive as superseded ``slug`` claims.
   Accept only an unambiguous match (exactly one surviving target row ever
   claimed that slug). No such fallback exists for ``Location.parent``
   (``location_path`` is claims_exempt — never claimed).
4. Anything else — unresolvable, ambiguous, or a non-string non-int value —
   **fails the whole migration** with a full report. The migration is atomic,
   so nothing partial lands; live rot needs a human decision (repair via
   patch or retract) before deploying.
"""

from __future__ import annotations

from collections import defaultdict

from django.db import migrations, models

# Location.parent claims stored the parent's derived ``location_path``; every
# other FK claim stored the target's ``slug``. Frozen snapshot — historical
# models carry no ``public_id_field``/ClassVars.
LOOKUP_OVERRIDES: dict[tuple[str, str], dict[str, str]] = {
    ("catalog", "location"): {"parent": "location_path"},
}

_BATCH_SIZE = 1000


def _history_resolve(Claim, ContentType, target_model, lookup, unresolved):
    """Map former public_ids to target PKs via superseded lookup-field claims.

    Returns ``(resolved: dict[str, int], ambiguous: set[str])``. A value is
    resolved only when exactly one *surviving* target row ever claimed it.
    """
    try:
        target_ct = ContentType.objects.get(
            app_label=target_model._meta.app_label,
            model=target_model._meta.model_name,
        )
    except ContentType.DoesNotExist:
        return {}, set()

    existing_pks = set(target_model.objects.values_list("pk", flat=True))
    candidates: dict[str, set[int]] = defaultdict(set)
    history = Claim.objects.filter(
        content_type_id=target_ct.pk, field_name=lookup
    ).values_list("value", "object_id")
    for value, object_id in history.iterator():
        if not isinstance(value, str):
            continue
        # Historical slug claims stored the authored value verbatim too —
        # match on the same trimmed form the caller's *unresolved* set uses.
        key = value.strip()
        if key in unresolved and object_id in existing_pks:
            candidates[key].add(object_id)

    resolved = {v: next(iter(pks)) for v, pks in candidates.items() if len(pks) == 1}
    ambiguous = {v for v, pks in candidates.items() if len(pks) > 1}
    return resolved, ambiguous


def convert_fk_claim_values(apps, schema_editor):
    Claim = apps.get_model("provenance", "Claim")
    ContentType = apps.get_model("contenttypes", "ContentType")

    failures: list[str] = []
    to_update: list = []

    ct_ids = (
        Claim.objects.order_by()
        .values_list("content_type_id", flat=True)
        .distinct()
    )
    for ct_id in ct_ids:
        ct = ContentType.objects.get(pk=ct_id)
        subject_model = apps.get_model(ct.app_label, ct.model)
        overrides = LOOKUP_OVERRIDES.get((ct.app_label, ct.model), {})

        for field in subject_model._meta.get_fields():
            if not isinstance(field, models.ForeignKey):
                continue
            target_model = field.related_model
            rows = list(
                Claim.objects.filter(
                    content_type_id=ct_id, field_name=field.name
                ).values_list("pk", "value", "object_id", "is_active")
            )
            if not rows:
                continue

            lookup = overrides.get(field.name, "slug")
            # Normalize exactly as the retired resolution path did (str-cast +
            # trim): the old write path stored the *authored* value verbatim,
            # so padded strings (" solid-state ") and YAML-numeric slugs
            # (stored as ints) both previously validated and resolved. Every
            # lookup below — current table, slug-claim history, final match —
            # keys on the trimmed form.
            str_keys = {
                v.strip() for _, v, _, _ in rows if isinstance(v, str) and v.strip()
            }
            int_values = {v for _, v, _, _ in rows if type(v) is int}
            probe_keys = str_keys | {str(v) for v in int_values}
            pk_by_key: dict[str, int] = {}
            ambiguous: set[str] = set()
            if probe_keys:
                pk_by_key = dict(
                    target_model.objects.filter(
                        **{f"{lookup}__in": probe_keys}
                    ).values_list(lookup, "pk")
                )
                # History fallback covers int-derived keys too: a YAML-numeric
                # slug whose target was later renamed resolves only through
                # the superseded slug claim, same as its string twin.
                unresolved = probe_keys - pk_by_key.keys()
                if unresolved:
                    from_history, ambiguous = _history_resolve(
                        Claim, ContentType, target_model, lookup, unresolved
                    )
                    pk_by_key.update(from_history)
            # Ints that are live PKs of the target table — used to tell a
            # legacy YAML-numeric slug from an already-converted PK.
            existing_int_pks: set[int] = (
                set(
                    target_model.objects.filter(pk__in=int_values).values_list(
                        "pk", flat=True
                    )
                )
                if int_values
                else set()
            )

            for claim_pk, value, object_id, is_active in rows:
                if value is None or value == "":
                    continue  # cleared
                if type(value) is int:
                    # Usually an already-converted PK (idempotent re-run) —
                    # but the old write path stored YAML-numeric slugs as
                    # ints, so an int whose str form matches a target slug
                    # needs a decision:
                    #   - not a live PK, str form is a slug → legacy numeric
                    #     slug: convert to that row's PK.
                    #   - a live PK *and* str form names a different row →
                    #     genuinely ambiguous: fail for a human call. (A
                    #     re-run can only trip this if a converted PK's str
                    #     form collides with another row's slug — then a human
                    #     confirming the value is already a PK is the fix.)
                    #   - otherwise → already a PK; leave as-is.
                    slug_pk = pk_by_key.get(str(value))
                    if slug_pk is not None and slug_pk != value:
                        if value in existing_int_pks:
                            failures.append(
                                f"claim pk={claim_pk} {ct.app_label}.{ct.model}"
                                f"(object_id={object_id}).{field.name} "
                                f"is_active={is_active}: int value {value!r} is "
                                f"both a live {target_model._meta.object_name} PK "
                                f"and (as a string) the {lookup} of PK {slug_pk} "
                                f"— cannot tell a legacy numeric slug from a "
                                f"converted PK"
                            )
                        else:
                            to_update.append(Claim(pk=claim_pk, value=slug_pk))
                    continue
                if not isinstance(value, str):
                    failures.append(
                        f"claim pk={claim_pk} {ct.app_label}.{ct.model}"
                        f"(object_id={object_id}).{field.name} is_active={is_active}: "
                        f"malformed value {value!r}"
                    )
                    continue
                key = value.strip()
                if not key:
                    # Whitespace-only normalized to "resolves to nothing" on
                    # the old path — a clear. Canonicalize to the "" sentinel
                    # so the row satisfies the new int | "" | None invariant
                    # instead of tripping the resolver's legacy-data warning.
                    to_update.append(Claim(pk=claim_pk, value=""))
                    continue
                target_pk = pk_by_key.get(key)
                if target_pk is None:
                    reason = "ambiguous slug history" if key in ambiguous else (
                        f"no {target_model._meta.object_name} with "
                        f"{lookup}={key!r} (current or via slug-claim history)"
                    )
                    failures.append(
                        f"claim pk={claim_pk} {ct.app_label}.{ct.model}"
                        f"(object_id={object_id}).{field.name} is_active={is_active}: "
                        f"{reason}"
                    )
                    continue
                to_update.append(Claim(pk=claim_pk, value=target_pk))

    if failures:
        report = "\n  ".join(failures)
        raise RuntimeError(
            f"Cannot convert {len(failures)} FK claim value(s) to PKs — repair "
            f"or retract these claims before migrating:\n  {report}"
        )

    Claim.objects.bulk_update(to_update, ["value"], batch_size=_BATCH_SIZE)


class Migration(migrations.Migration):
    dependencies = [
        ("provenance", "0025_alter_claim_claim_key_alter_claim_value"),
        ("contenttypes", "0002_remove_content_type_name"),
        # Latest catalog migration at authoring time, so every FK claim field
        # (incl. the recently added lineage FKs) exists on the historical models.
        ("catalog", "0018_machinemodel_licensed_build_of_and_more"),
    ]

    operations = [
        migrations.RunPython(convert_fk_claim_values, migrations.RunPython.noop),
    ]
