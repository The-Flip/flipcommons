"""The analytics entity-registry codegen channel and its drift guard.

The parity test compares the committed artifact to a fresh run. `make codegen`
is a local step CI doesn't run, so without it, adding a ``LinkableModel`` and
forgetting to regenerate leaves that entity's claims resolving to NULL — which
reads as "this subject has no name" rather than as an error. Byte parity,
because nothing reformats this file after the generator writes it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.catalog.management.commands.export_entity_registry import (
    OUTPUT_PATH,
    _require_columns,
    _require_lifecycle,
)
from apps.catalog.models import MachineModel
from apps.core.entity_types import all_linkable_models
from apps.provenance.models import Claim, ClaimControlledModel

COMMITTED_SQL = Path(settings.BASE_DIR).parent / OUTPUT_PATH


@pytest.fixture
def output(tmp_path: Path, settings) -> str:
    """Run the command into a temp tree and return the generated SQL."""
    settings.BASE_DIR = tmp_path / "backend"
    call_command("export_entity_registry")
    return (tmp_path / OUTPUT_PATH).read_text()


def _subject_models() -> list[type[ClaimControlledModel]]:
    return [
        cls for cls in all_linkable_models() if issubclass(cls, ClaimControlledModel)
    ]


def test_every_claim_subject_gets_a_union_branch(output: str) -> None:
    """A missing branch is invisible until the first claim about that entity."""
    for cls in _subject_models():
        assert f"FROM fc.{cls._meta.db_table}" in output, cls.__name__


def test_every_entity_gets_a_registry_row(output: str) -> None:
    registry_block = output.split("CREATE OR REPLACE VIEW entity_registry", 1)[1].split(
        "COMMENT ON VIEW", 1
    )[0]
    for cls in all_linkable_models():
        assert f"('{cls.entity_type}'" in registry_block, cls.__name__
        assert f"'{cls._meta.label_lower}'" in registry_block, cls.__name__


def test_public_id_field_is_honoured_per_entity(output: str) -> None:
    """Location addresses by ``location_path``; live places share the slug `victoria`."""
    assert "id, location_path, name, status FROM fc.catalog_location" in output
    assert "id, slug, name, status FROM fc.catalog_person" in output


def test_subject_types_use_the_public_spelling(output: str) -> None:
    """No content-type label reaches ``subject_type``; only ``django_label`` holds one."""
    subjects_block = output.split("CREATE OR REPLACE VIEW entity_subjects", 1)[1]
    assert "catalog." not in subjects_block


def test_a_subject_without_lifecycle_fails_codegen() -> None:
    with pytest.raises(CommandError, match="LifecycleStatusModel"):
        _require_lifecycle(Claim)


def test_every_claim_subject_has_lifecycle_today() -> None:
    for cls in _subject_models():
        _require_lifecycle(cls)


def test_a_subject_missing_an_identity_column_fails_codegen() -> None:
    with pytest.raises(CommandError, match="location_path"):
        _require_columns(MachineModel, {"location_path"})


def test_committed_file_matches_the_models(output: str) -> None:
    """`make codegen` was run after the last model change."""
    assert output == COMMITTED_SQL.read_text(), (
        f"{OUTPUT_PATH} is stale — run `make codegen`."
    )
