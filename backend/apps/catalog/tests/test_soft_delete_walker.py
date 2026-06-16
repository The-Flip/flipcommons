"""Unit tests for the generic soft-delete planner.

The walker is deliberately decoupled from any specific entity type — it
classifies each incoming FK by ``on_delete`` and the presence of
``LifecycleStatusModel`` on the referrer. These tests exercise that logic
through Title and MachineModel because they're the first real callers.
"""

from __future__ import annotations

import pytest

from apps.accounts.test_factories import make_user
from apps.catalog.api.soft_delete import (
    SoftDeleteBlockedError,
    execute_soft_delete,
    plan_soft_delete,
)
from apps.catalog.models import (
    GameplayFeature,
    MachineModel,
    Tag,
    TechnologyGeneration,
    TechnologySubgeneration,
    Theme,
    Title,
)
from apps.provenance.models import Claim, Source

pytestmark = pytest.mark.django_db


@pytest.fixture
def bootstrap_source(db):
    """Low-priority source used to seed name claims so the resolver doesn't
    blank the ``name`` column when a status claim is written during delete."""
    return Source.objects.create(
        name="Bootstrap", slug="bootstrap", source_type="editorial", priority=1
    )


def _title(
    slug: str, *, status: str = "active", name: str | None = None, source=None
) -> Title:
    label = name or slug.replace("-", " ").title()
    t = Title.objects.create(name=label, slug=slug, status=status)
    if source is not None:
        Claim.objects.assert_claim(t, "name", label, source=source)
    return t


def _model(
    title: Title,
    slug: str,
    *,
    status: str = "active",
    variant_of: MachineModel | None = None,
    source=None,
) -> MachineModel:
    label = slug.replace("-", " ").title()
    m = MachineModel.objects.create(
        title=title,
        name=label,
        slug=slug,
        status=status,
        variant_of=variant_of,
    )
    if source is not None:
        Claim.objects.assert_claim(m, "name", label, source=source)
    return m


class TestPlanCascade:
    def test_title_with_no_models(self):
        t = _title("lonely")
        plan = plan_soft_delete(t)
        assert not plan.is_blocked
        assert plan.entities_to_delete == [t]

    def test_title_cascades_to_active_models(self):
        t = _title("mm")
        pro = _model(t, "mm-pro")
        le = _model(t, "mm-le")
        plan = plan_soft_delete(t)
        assert not plan.is_blocked
        assert set(plan.entities_to_delete) == {t, pro, le}
        # Title is first in the cascade order (parent-before-child).
        assert plan.entities_to_delete[0] == t

    def test_already_deleted_children_not_in_cascade(self):
        t = _title("mm")
        _model(t, "mm-pro", status="deleted")
        live = _model(t, "mm-le")
        plan = plan_soft_delete(t)
        assert set(plan.entities_to_delete) == {t, live}


class TestProtectBlocker:
    def test_active_cross_title_variant_blocks(self):
        """A PROTECT referrer from outside the cascade tree blocks delete."""
        other_title = _title("other")
        target_title = _title("target")
        target_model = _model(target_title, "target-pro")
        _model(other_title, "other-variant", variant_of=target_model)

        plan = plan_soft_delete(target_title)
        assert plan.is_blocked
        assert len(plan.blockers) == 1
        blocker = plan.blockers[0]
        assert blocker.entity_type == "model"
        assert blocker.slug == "other-variant"
        assert blocker.relation == "variant_of"
        assert blocker.blocked_target_slug == "target-pro"

    def test_internal_variant_does_not_block(self):
        """Variant within the same cascade tree cascades with its parent."""
        t = _title("mm")
        pro = _model(t, "mm-pro")
        _model(t, "mm-le", variant_of=pro)
        plan = plan_soft_delete(t)
        assert not plan.is_blocked
        assert len(plan.entities_to_delete) == 3

    def test_soft_deleted_variant_does_not_block(self):
        """A PROTECT referrer is ignored once its own status is deleted."""
        other_title = _title("other")
        target_title = _title("target")
        target_model = _model(target_title, "target-pro")
        _model(other_title, "zombie-variant", variant_of=target_model, status="deleted")

        plan = plan_soft_delete(target_title)
        assert not plan.is_blocked

    def test_abbreviation_cascade_child_does_not_block(self):
        """Abbreviations are CASCADE + no-status; they ride with the parent."""
        from apps.catalog.models import TitleAbbreviation

        t = _title("mm")
        TitleAbbreviation.objects.create(title=t, value="MM")
        plan = plan_soft_delete(t)
        assert not plan.is_blocked


class TestUsageBlockers:
    """Active lifecycle entities reachable via M2M through-rows or self-ref
    hierarchy must block delete. These references are invisible to the FK
    PROTECT walker because the intermediate through-table has no lifecycle.
    The model-level ``soft_delete_usage_blockers`` opt-in declares which
    reverse managers to check.
    """

    def test_tag_blocked_by_active_machine_model_via_m2m(self):
        """Tag delete blocks while an active MachineModel has it applied."""
        tag = Tag.objects.create(name="Widebody", slug="widebody", status="active")
        title = _title("mm")
        mm = _model(title, "mm-pro")
        mm.tags.add(tag)

        plan = plan_soft_delete(tag)
        assert plan.is_blocked
        assert any(
            b.entity_type == "model" and b.slug == "mm-pro" for b in plan.blockers
        )

    def test_tag_not_blocked_by_soft_deleted_machine_model(self):
        """Soft-deleted referrer must not block — mirrors the FK PROTECT rule."""
        tag = Tag.objects.create(name="Widebody", slug="widebody", status="active")
        title = _title("mm")
        mm = _model(title, "mm-pro", status="deleted")
        mm.tags.add(tag)

        plan = plan_soft_delete(tag)
        assert not plan.is_blocked

    def test_theme_blocked_by_active_machine_model(self):
        theme = Theme.objects.create(name="Sports", slug="sports", status="active")
        title = _title("mm")
        mm = _model(title, "mm-pro")
        mm.themes.add(theme)

        plan = plan_soft_delete(theme)
        assert plan.is_blocked
        assert any(b.slug == "mm-pro" for b in plan.blockers)

    def test_theme_blocked_by_active_child_theme(self):
        """Self-ref hierarchy — a parent Theme can't be deleted while an
        active child points at it via ``Theme.parents``."""
        parent = Theme.objects.create(name="Sports", slug="sports", status="active")
        child = Theme.objects.create(name="Football", slug="football", status="active")
        child.parents.add(parent)

        plan = plan_soft_delete(parent)
        assert plan.is_blocked
        assert any(b.slug == "football" for b in plan.blockers)

    def test_theme_not_blocked_by_soft_deleted_child(self):
        parent = Theme.objects.create(name="Sports", slug="sports", status="active")
        child = Theme.objects.create(name="Football", slug="football", status="deleted")
        child.parents.add(parent)

        plan = plan_soft_delete(parent)
        assert not plan.is_blocked

    def test_gameplay_feature_blocked_by_active_machine_model(self):
        feature = GameplayFeature.objects.create(
            name="Multiball", slug="multiball", status="active"
        )
        title = _title("mm")
        mm = _model(title, "mm-pro")
        mm.gameplay_features.add(feature)

        plan = plan_soft_delete(feature)
        assert plan.is_blocked
        assert any(b.slug == "mm-pro" for b in plan.blockers)

    def test_gameplay_feature_blocked_by_active_child(self):
        parent = GameplayFeature.objects.create(
            name="Ramps", slug="ramps", status="active"
        )
        child = GameplayFeature.objects.create(
            name="Spinning Ramp", slug="spinning-ramp", status="active"
        )
        child.parents.add(parent)

        plan = plan_soft_delete(parent)
        assert plan.is_blocked
        assert any(b.slug == "spinning-ramp" for b in plan.blockers)

    def test_title_cascade_with_tagged_children_not_self_blocked(
        self, bootstrap_source
    ):
        """Title delete cascades to its MachineModels. Each model's tags
        look referenced-by-an-active-model during walk — but the model is
        itself in the cascade set, so the existing dedup must continue to
        skip it. Regression guard on the cascade filter at
        ``plan_soft_delete`` (soft_delete.py) interacting with the new
        usage-blocker rule.
        """
        tag = Tag.objects.create(name="Widebody", slug="widebody", status="active")
        t = _title("mm", source=bootstrap_source)
        mm = _model(t, "mm-pro", source=bootstrap_source)
        mm.tags.add(tag)

        plan = plan_soft_delete(t)
        assert not plan.is_blocked
        assert set(plan.entities_to_delete) == {t, mm}


class TestExecute:
    def test_writes_status_deleted_claims(self, db, bootstrap_source):
        user = make_user(email="deleter@example.com")
        t = _title("mm", source=bootstrap_source)
        m = _model(t, "mm-pro", source=bootstrap_source)

        changeset, deleted = execute_soft_delete(t, user=user, note="cleanup")
        assert changeset is not None
        assert changeset.note == "cleanup"
        assert set(deleted) == {t, m}

        t.refresh_from_db()
        m.refresh_from_db()
        assert t.status == "deleted"
        assert m.status == "deleted"
        # All status=deleted claims share one changeset.
        claim_cs_ids = {c.changeset_id for c in t.claims.filter(field_name="status")}
        assert claim_cs_ids == {changeset.pk}

    def test_blocked_raises(self, db, bootstrap_source):
        user = make_user(email="deleter@example.com")
        other = _title("other", source=bootstrap_source)
        target = _title("target", source=bootstrap_source)
        pro = _model(target, "target-pro", source=bootstrap_source)
        _model(other, "blocker", variant_of=pro, source=bootstrap_source)

        with pytest.raises(SoftDeleteBlockedError) as exc:
            execute_soft_delete(target, user=user)
        assert exc.value.blockers[0].slug == "blocker"
        target.refresh_from_db()
        assert target.status == "active"


class TestCascadeToSubgenerations:
    """Soft-deleting a TechnologyGeneration cascades to its lifecycle
    subgenerations (CASCADE FK), so they aren't left active and orphaned under a
    deleted parent. Mirrored on DisplayType → DisplaySubtype; the policy is
    enforced at boot by check_soft_delete_policy (core.E114)."""

    def _gen_with_sub(self, *, sub_status: str = "active"):
        gen = TechnologyGeneration.objects.create(
            name="Solid State", slug="solid-state", status="active"
        )
        sub = TechnologySubgeneration.objects.create(
            name="MPU", slug="mpu", status=sub_status, technology_generation=gen
        )
        return gen, sub

    def test_generation_cascades_to_active_subgeneration(self):
        gen, sub = self._gen_with_sub()
        plan = plan_soft_delete(gen)
        assert not plan.is_blocked
        assert set(plan.entities_to_delete) == {gen, sub}

    def test_soft_deleted_subgeneration_not_in_cascade(self):
        gen, _ = self._gen_with_sub(sub_status="deleted")
        plan = plan_soft_delete(gen)
        assert plan.entities_to_delete == [gen]

    def test_subgeneration_used_by_active_model_blocks_both_deletes(self):
        """A subgeneration referenced by an active machine blocks its own delete
        (direct PROTECT) and the parent generation's delete (the cascade pulls
        the subgeneration in, surfacing its PROTECT referrer)."""
        gen, sub = self._gen_with_sub()
        mm = _model(_title("mm"), "mm-pro")
        mm.technology_subgeneration = sub
        mm.save()

        child_plan = plan_soft_delete(sub)
        assert child_plan.is_blocked
        assert any(b.slug == "mm-pro" for b in child_plan.blockers)

        parent_plan = plan_soft_delete(gen)
        assert parent_plan.is_blocked
        assert any(b.slug == "mm-pro" for b in parent_plan.blockers)
