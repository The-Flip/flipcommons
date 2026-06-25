"""Guards for the cite-marker rewrite migration (0007).

Two risks the migration carries:

1. The frozen ``MARKDOWN_FIELDS`` list silently falls out of date when a new
   markdown field is added (``get_markdown_fields`` can't be used at migration
   runtime — ``MarkdownField`` deconstructs to a plain ``TextField``).
2. The forward/reverse rewrite must actually find both surfaces — entity
   markdown columns and ``Claim.value`` — and round-trip cleanly.
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps as django_apps
from django.contrib.contenttypes.models import ContentType

from apps.core.markdown.field import get_markdown_fields
from apps.provenance.models import Claim, Source
from apps.provenance.test_factories import source_changeset

_migration = importlib.import_module(
    "apps.provenance.migrations.0007_rewrite_cite_markers"
)


def test_frozen_markdown_field_list_matches_live_set():
    """The migration's frozen list must equal the live markdown-field set."""
    frozen = set(_migration.MARKDOWN_FIELDS)
    live = {
        (model._meta.app_label, model.__name__, field)
        for model in django_apps.get_models()
        for field in get_markdown_fields(model)
    }
    assert frozen == live, (
        "Markdown fields changed since migration 0007 was written. 0007 already "
        "ran, so DON'T edit its frozen list — instead decide whether the changed "
        "field needs its own cite-marker backfill (a brand-new field never held "
        "legacy [[cite:N]] markers, so usually not), then reconcile the expected "
        "set below. This tripwire exists because get_markdown_fields can't be "
        "called at migration runtime (MarkdownField deconstructs to TextField), "
        "so the snapshot must be frozen and a drift can't be caught any other way."
    )


@pytest.mark.django_db
def test_forward_and_reverse_rewrite_entity_and_claim():
    from apps.catalog.models import Manufacturer

    mfr = Manufacturer.objects.create(
        name="Acme", slug="acme", description="A fact.[[cite:7]] Another.[[cite:9]]"
    )
    src = Source.objects.create(
        name="Editorial", slug="editorial-x", source_type="editorial"
    )
    # Direct create (not make_claim) to seed the legacy [[cite:N]] value the
    # migration rewrites — make_claim would reject it via markdown validation.
    # actor + changeset are NOT NULL, so supply a source changeset and its actor.
    claim = Claim.objects.create(
        content_type=ContentType.objects.get_for_model(Manufacturer),
        object_id=mfr.pk,
        actor=src.actor,
        changeset=source_changeset(src),
        field_name="description",
        claim_key="description",
        value="A fact.[[cite:7]]",
    )

    _migration._forward(django_apps, None)

    mfr.refresh_from_db()
    claim.refresh_from_db()
    assert mfr.description == "A fact.[[cite:id:7]] Another.[[cite:id:9]]"
    assert claim.value == "A fact.[[cite:id:7]]"

    _migration._reverse(django_apps, None)

    mfr.refresh_from_db()
    claim.refresh_from_db()
    assert mfr.description == "A fact.[[cite:7]] Another.[[cite:9]]"
    assert claim.value == "A fact.[[cite:7]]"
