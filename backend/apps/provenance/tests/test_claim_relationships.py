"""The relationship declaration vocabulary — structure + read-surface smoke tests.

No through-model declares a ``claim_relationship_spec`` yet, so the read surface
returns nothing for every model. These tests pin that empty contract (guarding
against an accidental early consumer) and exercise the spec dataclasses.
"""

from __future__ import annotations

import pytest

from apps.provenance.model_bases import (
    ClaimRelationshipSpec,
    EmptyTargetPolicy,
    MemberField,
    PayloadField,
    ScopePolicy,
    SingleSubject,
    XorSubject,
    relationships_for,
)


def test_public_symbols_import_from_model_bases() -> None:
    """The vocabulary is reachable from the package root, not a private module."""
    from apps.provenance import model_bases

    for name in (
        "ClaimRelationshipBinding",
        "ClaimRelationshipSpec",
        "ClaimThroughModel",
        "EmptyTargetPolicy",
        "MemberField",
        "PayloadField",
        "ScopePolicy",
        "SingleSubject",
        "SubjectSpec",
        "XorSubject",
        "relationships_for",
    ):
        assert hasattr(model_bases, name), name


def test_spec_is_frozen_pure_data() -> None:
    """The spec and its parts are frozen dataclasses carrying no model reference."""
    spec = ClaimRelationshipSpec(
        namespace="example",
        subject=SingleSubject(fk_name="widget"),
        members=(MemberField(field="target", identity="target"),),
        payload=(PayloadField(field="count", nullable=True),),
    )
    assert spec.scope is ScopePolicy.SUBJECTS
    assert spec.members[0].empty_target is EmptyTargetPolicy.DROP_INVALID
    with pytest.raises(AttributeError):
        spec.namespace = "other"  # type: ignore[misc]


def test_xor_subject_holds_two_branches() -> None:
    subject = XorSubject(left_fk="model", right_fk="series")
    assert (subject.left_fk, subject.right_fk) == ("model", "series")


def test_relationships_for_is_empty_until_specs_declared() -> None:
    """No through-model declares a spec yet, so every subject resolves to ()."""
    from apps.catalog.models import CorporateEntity, MachineModel, Series, Title

    for model in (MachineModel, Series, Title, CorporateEntity):
        assert relationships_for(model) == ()
