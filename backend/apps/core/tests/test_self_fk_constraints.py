"""Asserts every self-referential FK in the system is barred from pointing at
its own row.

The rule is uniform: no record is its own variant, its own parent or its own
anything. Django knows which fields are self-FKs, so a new one can appear
without anyone remembering the rule applies to it — and nothing else would go
red, because a missing CHECK constraint only shows up as a row that should
never have existed. This walks the app registry so the omission is a CI
failure instead.

The API-level guard in ``machine_models.py`` is a nicer 422, not a substitute:
it covers one endpoint on one model, while the constraint covers every write
path including ingest and the admin.
"""

from __future__ import annotations

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import self_fk_field_names


def _self_fk_pairs() -> list[tuple[type[models.Model], str]]:
    """Every (model, self-FK field name) pair in the project, at import time."""
    return [
        (model, field_name)
        for model in apps.get_models()
        for field_name in self_fk_field_names(model)
    ]


def _pair_id(pair: tuple[type[models.Model], str]) -> str:
    model, field_name = pair
    return f"{model._meta.label}.{field_name}"


SELF_FK_PAIRS = _self_fk_pairs()


def test_the_self_fk_inventory_is_not_empty() -> None:
    """Guards the guard: a discovery bug would silently pass every test below
    by finding nothing to check."""
    assert SELF_FK_PAIRS


@pytest.mark.parametrize("pair", SELF_FK_PAIRS, ids=_pair_id)
def test_self_fk_has_a_not_self_constraint(
    pair: tuple[type[models.Model], str],
) -> None:
    model, field_name = pair
    expected = f"{model._meta.app_label}_{model._meta.model_name}_{field_name}_not_self"
    names = {c.name for c in model._meta.constraints}
    assert expected in names, (
        f"{model._meta.label}.{field_name} is a self-referential FK with no "
        f"{expected!r} constraint. Add "
        f'`self_fk_not_self({field_name!r}, message="…")` to '
        f"{model.__name__}.Meta.constraints and make the migration."
    )


@pytest.mark.parametrize("pair", SELF_FK_PAIRS, ids=_pair_id)
def test_not_self_constraint_rejects_a_self_reference(
    db, pair: tuple[type[models.Model], str]
) -> None:
    """The constraint is checked for what it does, not for how it's spelled —
    a condition that named the wrong field would pass an existence check."""
    model, field_name = pair
    expected = f"{model._meta.app_label}_{model._meta.model_name}_{field_name}_not_self"
    constraint = next(c for c in model._meta.constraints if c.name == expected)

    # Unsaved stand-ins: ``validate`` reads the field values off the instance
    # rather than looking the row up, so nothing needs to exist. The ``db``
    # fixture is still required — evaluating the condition compiles it to a
    # table-less SELECT and runs it.
    pointing_at_self = model(pk=1, **{f"{field_name}_id": 1})
    with pytest.raises(ValidationError):
        constraint.validate(model, pointing_at_self)

    pointing_elsewhere = model(pk=1, **{f"{field_name}_id": 2})
    constraint.validate(model, pointing_elsewhere)

    unset = model(pk=1, **{f"{field_name}_id": None})
    constraint.validate(model, unset)


def test_flat_self_fks_is_a_subset_of_the_self_fk_inventory() -> None:
    """A ``flat_self_fks`` entry must name a real self-FK on its model, so a
    field rename can't leave a dead declaration that silently guards nothing."""
    from apps.provenance.models import ClaimControlledModel

    for model in apps.get_models():
        if not issubclass(model, ClaimControlledModel):
            continue
        assert model.flat_self_fks <= set(self_fk_field_names(model)), (
            f"{model._meta.label}.flat_self_fks names fields that are not "
            f"self-FKs on the model: "
            f"{model.flat_self_fks - set(self_fk_field_names(model))}"
        )


def test_variant_of_is_declared_flat() -> None:
    """Guards the guard: the declaration the whole feature hangs on."""
    from apps.catalog.models import MachineModel

    assert "variant_of" in MachineModel.flat_self_fks


@pytest.mark.parametrize("pair", SELF_FK_PAIRS, ids=_pair_id)
def test_not_self_constraint_is_validated_before_the_db(
    pair: tuple[type[models.Model], str],
) -> None:
    """``violation_error_code`` is what makes the claim resolver validate this
    constraint in Python (``apps.catalog.resolve``). Without it the resolver
    skips it, the write reaches the DB, and the resulting ``IntegrityError``
    is reported to the user as a unique-constraint violation — a 422 with the
    wrong explanation.
    """
    model, field_name = pair
    expected = f"{model._meta.app_label}_{model._meta.model_name}_{field_name}_not_self"
    constraint = next(c for c in model._meta.constraints if c.name == expected)
    assert constraint.violation_error_code == "cross_field"
