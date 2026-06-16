"""Tests for the ``check_soft_delete_policy`` system check.

The classifier (``_classify_soft_delete``) is pure over ``_SoftDeleteFacts``, so
each failure mode is exercised with synthetic facts rather than fabricated
Django models. ``test_real_models_pass`` is the acceptance test: the live model
graph must classify cleanly, which is what makes the check safe to register at
boot.
"""

from __future__ import annotations

from collections.abc import Sequence

from django.core.checks import CheckMessage, Error

from apps.core.checks import (
    _classify_soft_delete,
    _InboundRelation,
    _SoftDeleteFacts,
    check_soft_delete_policy,
)


def _fk(
    *,
    accessor: str | None,
    on_delete_handled: bool = True,
    on_delete_name: str = "PROTECT",
    referrer_is_lifecycle: bool = True,
    referrer_label: str = "app.Referrer",
    referrer_field: str = "target",
) -> _InboundRelation:
    return _InboundRelation(
        kind="fk",
        referrer_label=referrer_label,
        referrer_field=referrer_field,
        accessor=accessor,
        on_delete_name=on_delete_name,
        on_delete_handled=on_delete_handled,
        referrer_is_lifecycle=referrer_is_lifecycle,
    )


def _m2m(
    *,
    accessor: str | None,
    referrer_is_lifecycle: bool,
    referrer_label: str = "app.Referrer",
    referrer_field: str = "targets",
) -> _InboundRelation:
    return _InboundRelation(
        kind="m2m",
        referrer_label=referrer_label,
        referrer_field=referrer_field,
        accessor=accessor,
        on_delete_name=None,
        on_delete_handled=True,
        referrer_is_lifecycle=referrer_is_lifecycle,
    )


def _facts(
    *,
    inbound: Sequence[_InboundRelation] = (),
    forward_blocker_m2ms: Sequence[str] = (),
    usage_blockers: frozenset[str] = frozenset(),
    cascade_relations: frozenset[str] = frozenset(),
    label: str = "app.M",
) -> _SoftDeleteFacts:
    return _SoftDeleteFacts(
        label=label,
        inbound=tuple(inbound),
        forward_blocker_m2ms=tuple(forward_blocker_m2ms),
        usage_blockers=usage_blockers,
        cascade_relations=cascade_relations,
    )


def _ids(errors: list[CheckMessage]) -> set[str]:
    return {e.id for e in errors if isinstance(e, Error) and e.id is not None}


class TestUnhandledOnDelete:
    def test_handled_on_delete_passes(self):
        assert _classify_soft_delete(_facts(inbound=[_fk(accessor="m_set")])) == []

    def test_unhandled_on_delete_rejected(self):
        errors = _classify_soft_delete(
            _facts(
                inbound=[
                    _fk(
                        accessor="m_set",
                        on_delete_handled=False,
                        on_delete_name="SET_NULL",
                    )
                ]
            )
        )
        assert "core.E110" in _ids(errors)


class TestRedundantUsageBlocker:
    def test_usage_blocker_naming_reverse_fk_rejected(self):
        """ProductionStatus-shaped: a usage-blocker that is really a reverse FK.

        The PROTECT pass already covers it, so declaring it as a usage-blocker
        is redundant and double-reports the blocker.
        """
        errors = _classify_soft_delete(
            _facts(
                label="app.ProductionStatus",
                inbound=[_fk(accessor="machine_models")],
                usage_blockers=frozenset({"machine_models"}),
            )
        )
        assert "core.E111" in _ids(errors)


class TestMissingReverseM2MBlocker:
    def test_missing_m2m_usage_blocker_rejected(self):
        errors = _classify_soft_delete(
            _facts(
                inbound=[_m2m(accessor="machine_models", referrer_is_lifecycle=True)]
            )
        )
        assert "core.E112" in _ids(errors)

    def test_declared_m2m_usage_blocker_passes(self):
        errors = _classify_soft_delete(
            _facts(
                inbound=[_m2m(accessor="machine_models", referrer_is_lifecycle=True)],
                usage_blockers=frozenset({"machine_models"}),
            )
        )
        assert errors == []

    def test_m2m_from_non_lifecycle_does_not_require_blocker(self):
        """A through-table or non-lifecycle referrer can't be soft-deleted, so
        it never needs to block — no usage-blocker required."""
        errors = _classify_soft_delete(
            _facts(inbound=[_m2m(accessor="thing_set", referrer_is_lifecycle=False)])
        )
        assert errors == []

    def test_suppressed_m2m_accessor_does_not_require_blocker(self):
        """A reverse M2M with ``related_name="+"`` has no accessor to walk."""
        errors = _classify_soft_delete(
            _facts(inbound=[_m2m(accessor=None, referrer_is_lifecycle=True)])
        )
        assert errors == []


class TestCascadeFromLifecycle:
    """A CASCADE FK from a lifecycle child must be a declared cascade, else the
    child is orphaned on soft-delete (DB CASCADE never fires)."""

    def test_undeclared_cascade_from_lifecycle_rejected(self):
        errors = _classify_soft_delete(
            _facts(
                inbound=[
                    _fk(
                        accessor="subgenerations",
                        on_delete_name="CASCADE",
                        referrer_is_lifecycle=True,
                    )
                ]
            )
        )
        assert "core.E114" in _ids(errors)

    def test_declared_cascade_from_lifecycle_passes(self):
        errors = _classify_soft_delete(
            _facts(
                inbound=[
                    _fk(
                        accessor="subgenerations",
                        on_delete_name="CASCADE",
                        referrer_is_lifecycle=True,
                    )
                ],
                cascade_relations=frozenset({"subgenerations"}),
            )
        )
        assert errors == []

    def test_cascade_from_non_lifecycle_rides_along(self):
        """CASCADE from an owned non-lifecycle child needs no declaration."""
        errors = _classify_soft_delete(
            _facts(
                inbound=[
                    _fk(
                        accessor="alias_set",
                        on_delete_name="CASCADE",
                        referrer_is_lifecycle=False,
                    )
                ]
            )
        )
        assert errors == []


class TestForwardBlockerM2M:
    """A forward M2M to a lifecycle model with its reverse suppressed is the only
    path to active referrers, so it must be a usage-blocker."""

    def test_missing_forward_blocker_rejected(self):
        errors = _classify_soft_delete(
            _facts(forward_blocker_m2ms=["corporate_entities"])
        )
        assert "core.E115" in _ids(errors)

    def test_declared_forward_blocker_passes(self):
        errors = _classify_soft_delete(
            _facts(
                forward_blocker_m2ms=["corporate_entities"],
                usage_blockers=frozenset({"corporate_entities"}),
            )
        )
        assert errors == []


class TestUnclassifiedShape:
    def test_unclassified_shape_rejected(self):
        other = _InboundRelation(
            kind="other",
            referrer_label="app.Weird",
            referrer_field="thing",
            accessor="weird_set",
            on_delete_name=None,
            on_delete_handled=False,
            referrer_is_lifecycle=False,
        )
        errors = _classify_soft_delete(_facts(inbound=[other]))
        assert "core.E113" in _ids(errors)


class TestRealModels:
    """The live model graph must classify cleanly."""

    def test_real_models_pass(self):
        errors = check_soft_delete_policy(app_configs=None)
        assert errors == [], [str(e) for e in errors]
