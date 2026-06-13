"""Tests for the ``dump_patch_entry`` rehydration command.

Storage → patch-authoring is just ``convert_storage_to_authoring``
(``[[cite:id:N]]`` → ``[[cite:slug]]``). The command emits a complete, runnable
patch document so the gen pipeline / a human can reword a sentence and resubmit
with untouched citations intact. The load-bearing guarantee is byte-identity:
re-applying the unedited dump produces the same storage and diffs as a no-op.
"""

from __future__ import annotations

from io import StringIO

import pytest
import yaml
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.catalog.ingestion.apply import apply_plan
from apps.catalog.ingestion.patches import EditEntry, build_plan, load_patch
from apps.catalog.models import MachineModel
from apps.catalog.tests.conftest import make_machine_model
from apps.citation.models import CitationSource
from apps.core.markdown import convert_authoring_to_storage
from apps.provenance.models import CitationInstance, Claim, Source
from apps.provenance.test_factories import user_changeset

pytestmark = pytest.mark.django_db

User = get_user_model()


def _dump(entity_ref: str, *, attribution: str | None = None) -> str:
    out = StringIO()
    args = [entity_ref]
    if attribution is not None:
        args += ["--attribution", attribution]
    call_command("dump_patch_entry", *args, stdout=out)
    return out.getvalue()


def _description_of(doc_text: str) -> str:
    """Extract the description field from a dumped patch document."""
    doc = load_patch(doc_text)
    (entry,) = doc.claims
    assert isinstance(entry, EditEntry)
    value = entry.fields["description"]
    assert isinstance(value, str)
    return value


def _apply(text: str, *, patch_id: str = "0001-test") -> None:
    doc = load_patch(text)
    source = Source.objects.get(slug=doc.attribution)
    apply_plan(build_plan(doc, source=source, patch_id=patch_id))


def _stored_description(slug: str) -> str:
    claim = MachineModel.objects.get(slug=slug).claims.get(
        field_name="description", is_active=True
    )
    assert isinstance(claim.value, str)
    return claim.value


@pytest.fixture
def ipdb_root(db):
    return CitationSource.objects.create(
        name="Internet Pinball Database", source_type="web", identifier_key="ipdb"
    )


# ── round-trip byte-identity ───────────────────────────────────────


def test_round_trip_byte_identity_with_adversarial_text(flipcommons_catalog):
    """Dump → load → convert back equals the stored value, byte-for-byte.

    The text is deliberately hostile to PyYAML's literal-block style — blank
    lines, a trailing-two-spaces hard break, a leading-space line and no
    trailing newline — so it exercises the double-quoted fallback. It also
    carries non-ASCII characters (descriptions hold foreign-language quotes) to
    exercise ``allow_unicode=True`` under the byte-identity assertion.
    Byte-identity is style-independent, so correctness survives the readability
    cliff.
    """
    src = CitationSource.objects.create(
        name="IPDB", source_type="web", identifier_key="ipdb"
    )
    ci1 = CitationInstance.objects.create(citation_source=src, claim=None)
    ci2 = CitationInstance.objects.create(citation_source=src, claim=None)

    stored = (
        f"Gegründet by Günter — a café prototype.[[cite:id:{ci1.pk}]]\n"
        "\n"
        "Hard break here  \n"
        " leading-space line\n"
        f"End with no trailing newline.[[cite:id:{ci2.pk}]]"
    )
    pm = make_machine_model(name="Adversarial", slug="adversarial", description=stored)
    Claim.objects.assert_claim(pm, "description", stored, source=flipcommons_catalog)

    dumped = _dump("model.adversarial")
    authoring = _description_of(dumped)

    # Existing slugs are in place; no cites: map needed for a re-edit.
    assert f"[[cite:{ci1.slug}]]" in authoring
    assert f"[[cite:{ci2.slug}]]" in authoring
    assert convert_authoring_to_storage(authoring) == stored


def test_dump_is_runnable_no_op(flipcommons_catalog, ipdb_root):
    """Re-applying the unedited dump mints nothing and diffs as a no-op."""
    make_machine_model(name="Medieval Madness", slug="medieval-madness")
    _apply(
        """
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      description: "Solid-state classic.[[cite:1]] Few survive.[[cite:2]]"
      cites:
        '1': ipdb:4443
        '2': ipdb:9999
"""
    )
    instances_before = set(CitationInstance.objects.values_list("pk", flat=True))
    stored_before = _stored_description("medieval-madness")

    dumped = _dump("model.medieval-madness")
    _apply(dumped, patch_id="0002-reapply")

    assert (
        set(CitationInstance.objects.values_list("pk", flat=True)) == instances_before
    )
    assert _stored_description("medieval-madness") == stored_before


# ── attribution ────────────────────────────────────────────────────


def test_attribution_defaults_to_owning_source(flipcommons_catalog):
    pm = make_machine_model(name="Attar", slug="attar", description="Just text.")
    Claim.objects.assert_claim(
        pm, "description", "Just text.", source=flipcommons_catalog
    )

    doc = yaml.safe_load(_dump("model.attar"))
    assert doc["attribution"] == "flipcommons-catalog"


def test_attribution_override(flipcommons_catalog):
    other = Source.objects.create(
        slug="flipcommons-ai-desc-model", name="AI Desc", source_type="editorial"
    )
    pm = make_machine_model(name="Override", slug="override", description="Text.")
    Claim.objects.assert_claim(pm, "description", "Text.", source=flipcommons_catalog)

    doc = yaml.safe_load(_dump("model.override", attribution=other.slug))
    assert doc["attribution"] == "flipcommons-ai-desc-model"


def test_user_owned_winning_claim_requires_attribution(flipcommons_catalog):
    user = User.objects.create_user(username="editor", email="ed@example.com")
    pm = make_machine_model(name="UserEd", slug="user-ed", description="Hand edited.")
    Claim.objects.assert_claim(
        pm,
        "description",
        "Hand edited.",
        user=user,
        changeset=user_changeset(user),
    )

    with pytest.raises(CommandError, match="user-authored"):
        _dump("model.user-ed")

    # …but an explicit attribution forks it into a source-owned claim.
    doc = yaml.safe_load(_dump("model.user-ed", attribution="flipcommons-catalog"))
    assert doc["attribution"] == "flipcommons-catalog"


# ── errors ──────────────────────────────────────────────────────────


def test_unknown_entity_type_errors(db):
    with pytest.raises(CommandError):
        _dump("nonesuch.foo")


def test_malformed_ref_errors(db):
    with pytest.raises(CommandError, match="type.public_id"):
        _dump("model")


def test_no_such_entity_errors(flipcommons_catalog):
    with pytest.raises(CommandError, match="no such"):
        _dump("model.ghost")


def test_no_markdown_content_errors(flipcommons_catalog):
    make_machine_model(name="Empty", slug="empty")
    with pytest.raises(CommandError, match="no markdown content"):
        _dump("model.empty")
