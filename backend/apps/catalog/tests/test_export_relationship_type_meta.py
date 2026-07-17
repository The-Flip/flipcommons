"""The relationship-type-meta codegen channel and its drift guard.

Two jobs. The generator tests check the command emits the behavior table
faithfully. The parity test reads the **committed** artifact and compares it to
``RELATIONSHIP_TYPE_BEHAVIOR`` — the channel's real hazard, since `make codegen`
is a local step CI doesn't run: without this, flipping a flag and forgetting to
regenerate would ship a frontend that disagrees with backend validation (the
editor would offer a label rung the DB CHECK rejects). Parity is asserted on
parsed values, not bytes, so prettier's reformat of the committed file is
irrelevant.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command

from apps.catalog.models.model_relationship import (
    RELATIONSHIP_TYPE_BEHAVIOR,
    RelationshipType,
)

COMMITTED_META = (
    Path(settings.BASE_DIR).parent
    / "frontend"
    / "src"
    / "lib"
    / "entities"
    / "relationship-type-meta.ts"
)


def _parse_flags(source: str) -> dict[str, bool]:
    """`{relationship_type: requiresMachineTarget}` parsed from the TS source.

    Quote-agnostic so one parser reads both artifacts this test compares: the raw
    emitter output is double-quoted JSON (`"key": "copy"`), while the committed
    file has been through prettier (`key: 'copy'`).
    """
    return {
        key: value == "true"
        for key, value in re.findall(
            r"""["']?key["']?:\s*["']([a-z_]+)["'],\s*"""
            r"""["']?requiresMachineTarget["']?:\s*(true|false)""",
            source,
        )
    }


def _expected_flags() -> dict[str, bool]:
    return {
        t.value: RELATIONSHIP_TYPE_BEHAVIOR[t].requires_machine_target
        for t in RelationshipType
    }


@pytest.fixture
def generated(tmp_path: Path, settings) -> str:
    """Run the command into a temp tree and return the raw emitter output."""
    settings.BASE_DIR = tmp_path / "backend"
    call_command("export_relationship_type_meta")
    return (
        tmp_path / "frontend" / "src" / "lib" / "entities" / "relationship-type-meta.ts"
    ).read_text()


def test_generator_emits_every_type_with_its_behavior_flag(generated: str) -> None:
    assert _parse_flags(generated) == _expected_flags()


def test_generator_key_union_covers_every_type(generated: str) -> None:
    match = re.search(r"export type RelationshipTypeKey = ([^;]+);", generated)
    assert match, "RelationshipTypeKey union not found"
    emitted = set(re.findall(r"'([a-z_]+)'", match.group(1)))
    assert emitted == set(RelationshipType.values)


def test_committed_artifact_is_not_stale() -> None:
    """The committed file must already reflect the behavior table — `make codegen`
    is local-only, so a forgotten regeneration would otherwise reach the frontend."""
    assert COMMITTED_META.exists(), f"{COMMITTED_META} is missing — run `make codegen`."
    actual = _parse_flags(COMMITTED_META.read_text())
    assert actual == _expected_flags(), (
        "relationship-type-meta.ts is stale or hand-edited — run `make codegen`. "
        f"committed={json.dumps(actual, sort_keys=True)} "
        f"expected={json.dumps(_expected_flags(), sort_keys=True)}"
    )
