"""Regression tests: renaming an entity's slug must not break FK claims referencing it.

FK claim values store the target's PK, so a slug rename is invisible to
existing claims. These tests reproduce the pre-fix rot where FK claim
values held the target's slug: renaming a Title broke every
``MachineModel.title`` claim (IntegrityError on the NOT NULL FK), and
renaming a nullable FK's target silently dropped the link to NULL on the
next resolve.
"""

from __future__ import annotations

from apps.accounts.models import User
from apps.catalog.models import Title
from apps.catalog.models.series import Franchise
from apps.catalog.tests.conftest import make_machine_model
from apps.claim_edit.claim_write import execute_claims, validate_scalar_fields
from apps.provenance.models import ClaimControlledModel
from apps.provenance.resolution import resolve_after_mutation
from apps.provenance.test_factories import make_claim


def _edit(entity: ClaimControlledModel, fields: dict[str, object], user: User) -> None:
    """Write *fields* through the interactive PATCH boundary (slug-valued input)."""
    specs = validate_scalar_fields(type(entity), fields, entity=entity)
    execute_claims(entity, specs, user=user)


class TestSlugRenameDoesNotBreakFkClaims:
    def test_not_null_fk_survives_target_slug_rename(self, user: User) -> None:
        title = Title.objects.create(name="Medieval Madness", slug="medieval-madness")
        make_claim(title, "name", "Medieval Madness", user=user)
        pm = make_machine_model(name="Medieval Madness", slug="mm-machine", title=title)

        _edit(pm, {"title": "medieval-madness"}, user)
        pm.refresh_from_db()
        assert pm.title_id == title.pk

        _edit(title, {"slug": "medieval-madness-1997"}, user)
        title.refresh_from_db()
        assert title.slug == "medieval-madness-1997"

        # Pre-fix: the title claim held the old slug, so re-resolution set the
        # NOT NULL FK to None and raised IntegrityError on save.
        resolve_after_mutation(pm)
        pm.refresh_from_db()
        assert pm.title_id == title.pk

    def test_nullable_fk_survives_target_slug_rename(self, user: User) -> None:
        franchise = Franchise.objects.create(name="Addams Family", slug="addams-family")
        make_claim(franchise, "name", "Addams Family", user=user)
        title = Title.objects.create(name="The Addams Family", slug="taf")
        make_claim(title, "name", "The Addams Family", user=user)

        _edit(title, {"franchise": "addams-family"}, user)
        title.refresh_from_db()
        assert title.franchise_id == franchise.pk

        _edit(franchise, {"slug": "the-addams-family"}, user)

        # Pre-fix: the franchise claim held the old slug, so re-resolution
        # silently dropped the nullable FK to NULL.
        resolve_after_mutation(title)
        title.refresh_from_db()
        assert title.franchise_id == franchise.pk
