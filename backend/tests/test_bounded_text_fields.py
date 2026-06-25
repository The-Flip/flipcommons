"""Tests for ``BoundedTextField``, ``MarkdownField`` length caps, and a
meta-test that every installed model wired to either of those classes
carries the auto-generated CHECK constraint.

One triplet (positive DB / negative DB / negative schema) per mechanism
covers all callers — the meta-test below catches drift if a future
field is added without the corresponding constraint.
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, models, transaction
from django.db.models.constraints import CheckConstraint

from apps.accounts.models import User
from apps.catalog.models import Title
from apps.core.models import BoundedTextField
from apps.core.models.fields import DEFAULT_MARKDOWN_MAX_LENGTH, MarkdownField
from apps.provenance.models import ChangeSet, ChangeSetAction, CitationInstance
from apps.provenance.models.changeset import CHANGESET_NOTE_MAX_LENGTH
from apps.provenance.models.citation_instance import (
    CITATION_INSTANCE_LOCATOR_MAX_LENGTH,
)
from apps.provenance.schemas import ChangeSetInputSchema

# ---------------------------------------------------------------------------
# BoundedTextField — exercised via ChangeSet.note (cap = 1_000).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_bounded_text_field_accepts_exact_max_length() -> None:
    user = User.objects.create(username="bound_pos", email="bp@example.com")
    cs = ChangeSet.objects.create(
        actor=user.actor,
        action=ChangeSetAction.EDIT,
        note="x" * CHANGESET_NOTE_MAX_LENGTH,
    )
    assert len(cs.note) == CHANGESET_NOTE_MAX_LENGTH


@pytest.mark.django_db(transaction=True)
def test_bounded_text_field_rejects_overlong_at_db_layer() -> None:
    user = User.objects.create(username="bound_neg", email="bn@example.com")
    with pytest.raises(IntegrityError), transaction.atomic():
        ChangeSet.objects.create(
            actor=user.actor,
            action=ChangeSetAction.EDIT,
            note="x" * (CHANGESET_NOTE_MAX_LENGTH + 1),
        )


def test_bounded_text_field_schema_rejects_overlong() -> None:
    from pydantic import ValidationError as PydanticValidationError

    with pytest.raises(PydanticValidationError):
        ChangeSetInputSchema(note="x" * (CHANGESET_NOTE_MAX_LENGTH + 1))


# ---------------------------------------------------------------------------
# MarkdownField — exercised via Title.description (cap = 10_000 default).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_markdown_field_accepts_exact_max_length() -> None:
    cap = DEFAULT_MARKDOWN_MAX_LENGTH
    title = Title.objects.create(
        slug="cap-edge-pos",
        name="Cap Edge Positive",
        description="x" * cap,
    )
    assert len(title.description) == cap


@pytest.mark.django_db(transaction=True)
def test_markdown_field_rejects_overlong_at_db_layer() -> None:
    cap = DEFAULT_MARKDOWN_MAX_LENGTH
    with pytest.raises(IntegrityError), transaction.atomic():
        Title.objects.create(
            slug="cap-edge-neg",
            name="Cap Edge Negative",
            description="x" * (cap + 1),
        )


# ---------------------------------------------------------------------------
# CharField cap — CitationInstance.locator (cap = 200).
#
# Postgres enforces ``VARCHAR(N)`` at the column type level; the test DB is
# SQLite which doesn't. Verify the cap via the two layers we control:
# Django field validation (``full_clean()`` → ``ValidationError``) and the
# Ninja input schema (Pydantic → 422).
# ---------------------------------------------------------------------------


def test_citation_instance_create_schema_rejects_overlong_locator() -> None:
    from pydantic import ValidationError as PydanticValidationError

    from apps.provenance.schemas import CitationInstanceCreateSchema

    with pytest.raises(PydanticValidationError):
        CitationInstanceCreateSchema(
            citation_source_id=1,
            locator="x" * (CITATION_INSTANCE_LOCATOR_MAX_LENGTH + 1),
        )


@pytest.mark.django_db
def test_citation_instance_locator_rejects_overlong_in_full_clean() -> None:
    """``full_clean()`` enforces CharField max_length via Django validators."""
    from django.core.exceptions import ValidationError as DjangoValidationError

    from apps.citation.models import CitationSource

    src = CitationSource.objects.create(name="X", source_type="book")
    inst = CitationInstance(
        citation_source=src,
        locator="x" * (CITATION_INSTANCE_LOCATOR_MAX_LENGTH + 1),
    )
    with pytest.raises(DjangoValidationError):
        inst.full_clean()


# ---------------------------------------------------------------------------
# Meta-test: every BoundedTextField / MarkdownField has its CHECK.
# ---------------------------------------------------------------------------


def _iter_bounded_fields() -> list[
    tuple[type[models.Model], BoundedTextField | MarkdownField]
]:
    from django.apps import apps

    out: list[tuple[type[models.Model], BoundedTextField | MarkdownField]] = []
    for model in apps.get_models():
        for field in model._meta.get_fields():
            if isinstance(field, BoundedTextField | MarkdownField):
                out.append((model, field))
    return out


def test_every_bounded_field_has_max_length_check() -> None:
    """Auto-generated CHECK constraint must be present for every bounded field.

    Catches future regressions where ``contribute_to_class`` silently
    drops the constraint, or where a model overrides ``Meta.constraints``
    in a way that obliterates the appended check.
    """
    missing: list[str] = []
    for model, field in _iter_bounded_fields():
        expected_name = (
            f"{model._meta.app_label}_{model._meta.model_name}_{field.name}_max_length"
        )
        found = any(
            isinstance(c, CheckConstraint) and c.name == expected_name
            for c in model._meta.constraints
        )
        if not found:
            missing.append(
                f"{model.__name__}.{field.name} (expected {expected_name!r})"
            )
    assert not missing, "Missing max-length CHECK constraints:\n  " + "\n  ".join(
        missing
    )
