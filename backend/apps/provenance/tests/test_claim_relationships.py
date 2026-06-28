"""The relationship declaration vocabulary — structure + read-surface tests.

Exercises the spec dataclasses and the ``relationships_for`` read surface now
that the catalog through-models declare their specs (REF2).
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


def test_relationships_for_returns_declared_specs() -> None:
    """Each subject resolves to the namespaces its through-models declare."""
    from apps.catalog.models import CorporateEntity, MachineModel, Series, Title

    def namespaces(model: type) -> set[str]:
        return {b.spec.namespace for b in relationships_for(model)}

    assert namespaces(MachineModel) == {
        "theme",
        "tag",
        "reward_type",
        "gameplay_feature",
        "credit",
        "abbreviation",
    }
    assert namespaces(Title) == {"abbreviation"}
    assert namespaces(CorporateEntity) == {"location"}
    # Credit's XorSubject yields a binding on both subjects.
    assert namespaces(Series) == {"credit"}


def test_relationships_for_pairs_specs_with_accessors() -> None:
    """A binding carries the live accessor: M2M field name or reverse-FK name."""
    from apps.catalog.models import MachineModel

    by_namespace = {
        b.spec.namespace: b.accessor for b in relationships_for(MachineModel)
    }
    # M2M ``through=`` accessors.
    assert by_namespace["theme"] == "themes"
    assert by_namespace["gameplay_feature"] == "gameplay_features"
    # Reverse-FK accessors (the through rows *are* the members).
    assert by_namespace["credit"] == "credits"
    assert by_namespace["abbreviation"] == "abbreviations"


def test_relationships_for_xor_subject_spans_both_subjects() -> None:
    """Credit's ``XorSubject`` expands into one binding per subject model."""
    from apps.catalog.models import Credit, MachineModel, Series

    for model in (MachineModel, Series):
        credit = [b for b in relationships_for(model) if b.spec.namespace == "credit"]
        assert len(credit) == 1
        assert credit[0].subject_model is model
        assert credit[0].through_model is Credit
