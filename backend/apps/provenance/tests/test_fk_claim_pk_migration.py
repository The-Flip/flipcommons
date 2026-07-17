"""Guards for the FK-claim slug→PK conversion migration (0026).

The migration converts every FK scalar claim value from the target's
public_id string to its integer PK. Risks covered here:

1. Current-slug values convert; already-int and clear-sentinel values are
   untouched (idempotent re-run).
2. Stale slugs (target renamed since the claim was written) resolve through
   the target's superseded ``slug`` claim history — including retracted
   dependent claims, which revert can reactivate.
3. ``Location.parent`` values convert via ``location_path``.
4. Unresolvable or malformed values fail the whole migration with a report
   naming the offending claims (atomic — nothing partial lands).

Seed claims are created directly (not via ``make_claim``) because the live
write path now rejects string FK values — exactly the legacy shape this
migration exists to convert.
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps as django_apps
from django.contrib.contenttypes.models import ContentType

from apps.catalog.models import Location, MachineModel, TechnologyGeneration
from apps.provenance.models import Claim
from apps.provenance.test_factories import make_ingest_source, source_changeset

_migration = importlib.import_module(
    "apps.provenance.migrations.0026_fk_claim_values_to_pk"
)


@pytest.fixture
def src(db):
    return make_ingest_source(name="Legacy", slug="legacy", source_type="database")


def _legacy_claim(src, subject, field_name, value, *, is_active=True):
    claim = Claim.objects.create(
        content_type=ContentType.objects.get_for_model(type(subject)),
        object_id=subject.pk,
        actor=src.actor,
        changeset=source_changeset(src),
        field_name=field_name,
        claim_key=field_name,
        value=value,
    )
    if not is_active:
        # Sidestep the active-claim unique index / retraction bookkeeping;
        # the migration only reads pk/value/is_active.
        Claim.objects.filter(pk=claim.pk).update(is_active=False)
        claim.refresh_from_db()
    return claim


@pytest.mark.django_db
class TestFkClaimPkMigration:
    def test_current_slug_converts_to_pk(self, src):
        ss = TechnologyGeneration.objects.create(name="Solid State", slug="solid-state")
        pm = MachineModel.objects.create(
            name="M", slug="m", title=_title(), technology_generation=ss
        )
        claim = _legacy_claim(src, pm, "technology_generation", "solid-state")

        _migration.convert_fk_claim_values(django_apps, None)

        claim.refresh_from_db()
        assert claim.value == ss.pk

    def test_stale_slug_resolves_via_slug_claim_history(self, src):
        ss = TechnologyGeneration.objects.create(name="Solid State", slug="renamed")
        # Superseded slug claim records the former slug the dependent claim holds.
        _legacy_claim(src, ss, "slug", "solid-state", is_active=False)
        pm = MachineModel.objects.create(name="M", slug="m", title=_title())
        dependent = _legacy_claim(
            src, pm, "technology_generation", "solid-state", is_active=False
        )

        _migration.convert_fk_claim_values(django_apps, None)

        dependent.refresh_from_db()
        assert dependent.value == ss.pk

    def test_int_and_clear_sentinels_untouched(self, src):
        ss = TechnologyGeneration.objects.create(name="SS", slug="ss")
        pm = MachineModel.objects.create(name="M", slug="m", title=_title())
        already = _legacy_claim(src, pm, "technology_generation", ss.pk)
        cleared = _legacy_claim(src, pm, "display_type", "")

        _migration.convert_fk_claim_values(django_apps, None)

        already.refresh_from_db()
        cleared.refresh_from_db()
        assert already.value == ss.pk
        assert cleared.value == ""

    def test_location_parent_converts_via_location_path(self, src):
        usa = Location.objects.create(
            location_path="usa", slug="usa", name="USA", location_type="country"
        )
        il = Location.objects.create(
            location_path="usa/il",
            slug="il",
            name="Illinois",
            location_type="state",
            parent=usa,
        )
        claim = _legacy_claim(src, il, "parent", "usa")

        _migration.convert_fk_claim_values(django_apps, None)

        claim.refresh_from_db()
        assert claim.value == usa.pk

    def test_unresolvable_slug_fails_with_report(self, src):
        pm = MachineModel.objects.create(name="M", slug="m", title=_title())
        claim = _legacy_claim(src, pm, "technology_generation", "never-existed")

        with pytest.raises(RuntimeError, match="never-existed") as excinfo:
            _migration.convert_fk_claim_values(django_apps, None)
        assert f"claim pk={claim.pk}" in str(excinfo.value)

        # Atomic: nothing partial landed.
        claim.refresh_from_db()
        assert claim.value == "never-existed"

    def test_ambiguous_slug_history_fails(self, src):
        # Two surviving targets both once claimed the same slug — no safe pick.
        a = TechnologyGeneration.objects.create(name="A", slug="gen-a")
        b = TechnologyGeneration.objects.create(name="B", slug="gen-b")
        _legacy_claim(src, a, "slug", "shared-old-slug", is_active=False)
        _legacy_claim(src, b, "slug", "shared-old-slug", is_active=False)
        pm = MachineModel.objects.create(name="M", slug="m", title=_title())
        _legacy_claim(src, pm, "technology_generation", "shared-old-slug")

        with pytest.raises(RuntimeError, match="ambiguous"):
            _migration.convert_fk_claim_values(django_apps, None)

    def test_malformed_value_fails_with_report(self, src):
        pm = MachineModel.objects.create(name="M", slug="m", title=_title())
        _legacy_claim(src, pm, "technology_generation", ["not", "a", "slug"])

        with pytest.raises(RuntimeError, match="malformed"):
            _migration.convert_fk_claim_values(django_apps, None)

    def test_padded_slug_converts(self, src):
        # The old write path stored authored values verbatim and the old
        # resolver trimmed at lookup time, so a padded legacy value must
        # convert like a clean one.
        ss = TechnologyGeneration.objects.create(name="Solid State", slug="solid-state")
        pm = MachineModel.objects.create(name="M", slug="m", title=_title())
        claim = _legacy_claim(src, pm, "technology_generation", " solid-state ")

        _migration.convert_fk_claim_values(django_apps, None)

        claim.refresh_from_db()
        assert claim.value == ss.pk

    def test_padded_stale_slug_resolves_via_history(self, src):
        # Padded + renamed: normalization must apply to the history fallback
        # too, and the recorded slug claim may itself be padded.
        ss = TechnologyGeneration.objects.create(name="Solid State", slug="renamed")
        _legacy_claim(src, ss, "slug", "solid-state", is_active=False)
        pm = MachineModel.objects.create(name="M", slug="m", title=_title())
        dependent = _legacy_claim(src, pm, "technology_generation", " solid-state ")

        _migration.convert_fk_claim_values(django_apps, None)

        dependent.refresh_from_db()
        assert dependent.value == ss.pk

    def test_whitespace_only_value_canonicalized_to_clear_sentinel(self, src):
        # The old resolver normalized whitespace-only to "resolves to
        # nothing"; the migration canonicalizes it to the "" clear sentinel
        # so the row satisfies the new int | "" | None invariant.
        pm = MachineModel.objects.create(name="M", slug="m", title=_title())
        claim = _legacy_claim(src, pm, "display_type", "   ")

        _migration.convert_fk_claim_values(django_apps, None)

        claim.refresh_from_db()
        assert claim.value == ""

    def test_legacy_numeric_slug_converts(self, src):
        # YAML parsed a numeric slug as an int and the old path str-cast it at
        # lookup time. An int that is NOT a live PK but whose str form matches
        # a target slug is that legacy shape — convert it.
        gen = TechnologyGeneration.objects.create(name="1979 Gen", slug="1979")
        assert gen.pk != 1979
        pm = MachineModel.objects.create(name="M", slug="m", title=_title())
        claim = _legacy_claim(src, pm, "technology_generation", 1979)

        _migration.convert_fk_claim_values(django_apps, None)

        claim.refresh_from_db()
        assert claim.value == gen.pk

    def test_legacy_numeric_slug_resolves_via_history(self, src):
        # The renamed-target case for the numeric variant: int 1979 named a
        # slug that only survives as a superseded slug claim. The history
        # fallback must cover int-derived keys, not just string values.
        gen = TechnologyGeneration.objects.create(name="1979 Gen", slug="renamed")
        _legacy_claim(src, gen, "slug", "1979", is_active=False)
        assert gen.pk != 1979
        pm = MachineModel.objects.create(name="M", slug="m", title=_title())
        claim = _legacy_claim(src, pm, "technology_generation", 1979)

        _migration.convert_fk_claim_values(django_apps, None)

        claim.refresh_from_db()
        assert claim.value == gen.pk

    def test_int_that_is_both_pk_and_slug_fails(self, src):
        # An int that is simultaneously a live target PK and (as a string)
        # another row's slug is undecidable — fail for a human call.
        a = TechnologyGeneration.objects.create(name="A", slug="gen-a")
        TechnologyGeneration.objects.create(name="B", slug=str(a.pk))
        pm = MachineModel.objects.create(name="M", slug="m", title=_title())
        _legacy_claim(src, pm, "technology_generation", a.pk)

        with pytest.raises(RuntimeError, match="cannot tell"):
            _migration.convert_fk_claim_values(django_apps, None)


def _title():
    from apps.catalog.models import Title

    title, _ = Title.objects.get_or_create(
        slug="migration-title", defaults={"name": "Migration Title"}
    )
    return title
