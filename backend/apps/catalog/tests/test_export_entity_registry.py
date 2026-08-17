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
    _alias_rows,
    _require_columns,
    _require_lifecycle,
    _require_linkable,
)
from apps.catalog.models import MachineModel
from apps.core.entity_types import all_linkable_models
from apps.core.markdown import get_markdown_fields
from apps.core.models import LinkableModel
from apps.core.wikilinks import WikilinkableModel
from apps.provenance.models import Claim, ClaimControlledModel

COMMITTED_SQL = Path(settings.BASE_DIR).parent / OUTPUT_PATH


@pytest.fixture
def output(tmp_path: Path, settings) -> str:
    """Run the command into a temp tree and return the generated SQL."""
    settings.BASE_DIR = tmp_path / "backend"
    call_command("export_entity_registry")
    return (tmp_path / OUTPUT_PATH).read_text()


def _view_block(output: str, view: str) -> str:
    """The generated SQL for one view alone.

    Bounded at the next ``CREATE OR REPLACE``, so a view added after this one
    cannot drift into an assertion scoped to it.
    """
    tail = output.split(f"CREATE OR REPLACE VIEW {view}", 1)[1]
    return tail.split("CREATE OR REPLACE", 1)[0]


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


def test_is_wikilinkable_tracks_the_picker_base(output: str) -> None:
    """Location is addressable but absent from the wikilink picker.

    An analysis treating every entity as linkable reports unlinked mentions of
    records prose has no way to link, so the distinction has to reach SQL.
    """
    registry_block = output.split("CREATE OR REPLACE VIEW entity_registry", 1)[1].split(
        "COMMENT ON VIEW", 1
    )[0]
    for line in registry_block.splitlines():
        for cls in all_linkable_models():
            if line.strip().startswith(f"('{cls.entity_type}'"):
                expected = "true" if issubclass(cls, WikilinkableModel) else "false"
                assert line.rstrip(" ,)").endswith(expected), cls.__name__


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


def _prose_models() -> list[type[LinkableModel]]:
    return [cls for cls in all_linkable_models() if get_markdown_fields(cls)]


def test_every_markdown_field_gets_a_prose_branch(output: str) -> None:
    """A missing branch reads as "that entity has no prose", not as an error."""
    prose_block = _view_block(output, "entity_prose")
    for cls in _prose_models():
        for field in get_markdown_fields(cls):
            assert f"'{field}'" in prose_block, f"{cls.__name__}.{field}"
        assert f"_staging('fc.{cls._meta.db_table}')" in prose_block, cls.__name__


def test_prose_branches_read_through_staging(output: str) -> None:
    """The liveness rule stays spelled once, in the macro — never inlined here."""
    assert "IS DISTINCT FROM 'deleted'" not in output
    prose_block = _view_block(output, "entity_prose")
    assert "FROM fc.catalog_" not in prose_block


def test_an_entity_with_prose_but_no_lifecycle_fails_codegen() -> None:
    """``_staging()`` selects ``status`` away, so such a branch would fail to bind."""
    with pytest.raises(CommandError, match="LifecycleStatusModel"):
        _require_lifecycle(Claim)


def test_every_alias_type_gets_a_branch(output: str) -> None:
    """A missing branch reads as "that entity has no aliases", not as an error.

    Tied to the engine's registry by count, so registering an ``AliasModel``
    without regenerating fails here rather than silently narrowing the view.
    """
    from apps.catalog.engine.aliases import discover_alias_types

    alias_block = _view_block(output, "entity_aliases")
    rows = _alias_rows()
    assert len(rows) == len(discover_alias_types())
    for row in rows:
        assert f"FROM fc.{row.db_table}" in alias_block, row.entity_type
        assert row.fk_column in alias_block, row.entity_type
        assert f"'{row.entity_type}'" in alias_block, row.entity_type


def test_an_alias_parent_without_entity_type_fails_codegen() -> None:
    """``entity_aliases`` keys on ``entity_type``; a parent lacking one has nothing."""
    with pytest.raises(CommandError, match="not a LinkableModel"):
        _require_linkable(Claim)


def test_alias_branches_key_the_way_entity_subjects_does(output: str) -> None:
    """The pair has to match or the join to entity_subjects silently returns nothing."""
    alias_block = _view_block(output, "entity_aliases")
    assert "AS t(entity_type, entity_id, alias);" in alias_block


def test_committed_file_matches_the_models(output: str) -> None:
    """`make codegen` was run after the last model change."""
    assert output == COMMITTED_SQL.read_text(), (
        f"{OUTPUT_PATH} is stale — run `make codegen`."
    )
