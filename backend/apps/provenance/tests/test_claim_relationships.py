"""The relationship declaration vocabulary — structure + read-surface tests.

Exercises the spec dataclasses and the ``relationships_for`` read surface now
that the catalog through-models declare their specs.
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
    all_relationship_bindings,
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
        "all_relationship_bindings",
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
    from apps.catalog.models import (
        CorporateEntity,
        GameplayFeature,
        MachineModel,
        Series,
        Theme,
        Title,
    )
    from apps.provenance.models import ClaimControlledModel

    def namespaces(model: type[ClaimControlledModel]) -> set[str]:
        return {b.spec.namespace for b in relationships_for(model)}

    assert namespaces(MachineModel) == {
        "theme",
        "tag",
        "reward_type",
        "gameplay_feature",
        "credit",
        "abbreviation",
        "model_relationship",
    }
    assert namespaces(Title) == {"abbreviation"}
    assert namespaces(CorporateEntity) == {"location"}
    # Credit's XorSubject yields a binding on both subjects.
    assert namespaces(Series) == {"credit"}
    # Self-referential parent hierarchies: the subject is the entity itself, via
    # the ThemeParent / GameplayFeatureParent through-models.
    assert namespaces(Theme) == {"theme_parent"}
    assert namespaces(GameplayFeature) == {"gameplay_feature_parent"}


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


def test_relationships_for_self_parent_binding() -> None:
    """A promoted parent through-model resolves as a plain SingleSubject binding.

    The child FK is the subject, the parent FK is the identity member, and the
    accessor is the repointed ``parents`` M2M — no dedicated self-parent variant.
    """
    from apps.catalog.models import (
        GameplayFeature,
        GameplayFeatureParent,
        Theme,
        ThemeParent,
    )

    for model, through, subject_fk in (
        (Theme, ThemeParent, "from_theme"),
        (GameplayFeature, GameplayFeatureParent, "from_gameplayfeature"),
    ):
        bindings = relationships_for(model)
        assert len(bindings) == 1
        binding = bindings[0]
        assert binding.subject_model is model
        assert binding.through_model is through
        assert binding.subject_fk == subject_fk
        assert binding.accessor == "parents"


def test_relationships_for_xor_subject_spans_both_subjects() -> None:
    """Credit's ``XorSubject`` expands into one binding per subject model."""
    from apps.catalog.models import Credit, MachineModel, Series

    for model, expected_fk in ((MachineModel, "model"), (Series, "series")):
        credit = [b for b in relationships_for(model) if b.spec.namespace == "credit"]
        assert len(credit) == 1
        assert credit[0].subject_model is model
        assert credit[0].through_model is Credit
        # The binding resolves which XOR branch this subject occupies, so the
        # resolution builder derives ``{subject_fk}_id`` without re-introspecting.
        assert credit[0].subject_fk == expected_fk


def test_binding_subject_fk_matches_single_subject() -> None:
    """A SingleSubject binding carries the declared subject FK name."""
    from apps.catalog.models import MachineModel

    by_namespace = {
        b.spec.namespace: b.subject_fk for b in relationships_for(MachineModel)
    }
    assert by_namespace["theme"] == "machinemodel"
    assert by_namespace["abbreviation"] == "machine_model"


def test_all_relationship_bindings_is_the_union_of_relationships_for() -> None:
    """The flat query equals every subject's ``relationships_for`` combined.

    The schema + resolution derivations iterate this set; it must lose nothing.
    """
    from apps.catalog._walks import catalog_models

    flat = all_relationship_bindings()
    per_subject = [b for model in catalog_models() for b in relationships_for(model)]
    assert set(flat) == set(per_subject)
    assert len(flat) == len(per_subject)  # no duplicates
    # Credit's XOR yields two bindings; abbreviation spans two through-models;
    # the two self-referential parent hierarchies add one binding each.
    namespaces = sorted(b.spec.namespace for b in flat)
    assert namespaces == [
        "abbreviation",
        "abbreviation",
        "credit",
        "credit",
        "gameplay_feature",
        "gameplay_feature_parent",
        "location",
        "model_relationship",
        "reward_type",
        "tag",
        "theme",
        "theme_parent",
    ]
