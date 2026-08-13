"""Drift guard for the citation-type-meta codegen channel.

The parity tests read the **committed** artifact and compare it to
``CITATION_TYPE_SPECS`` — the channel's real hazard, since `make codegen` is a
local step CI doesn't run: without this, registering a citation type (or
flipping a locator kind) and forgetting to regenerate would ship a frontend
whose locator UX disagrees with backend validation. Parity is asserted on
parsed values, not bytes, so prettier's reformat of the committed file is
irrelevant.

Only the fields a stale artifact would make the frontend act on are pinned: the
key union, plus each type's declarative flags (``locatorKind`` drives the input
behavior, ``childSkipsLocator`` drives whether the locator field appears,
``slugAddressed`` drives whether authored sources require a slug, and
``authoredRootCreation`` drives which types the create-stage picker offers).
The copy fields (labels, help, placeholders, the child noun) are prose the
emitter passes through, and prettier wraps them across lines — pinning them
would buy little and cost a brittle parser.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import NamedTuple

from django.conf import settings

from apps.citation.citation_types import CITATION_TYPE_SPECS

COMMITTED_META = (
    Path(settings.BASE_DIR).parent
    / "frontend"
    / "src"
    / "lib"
    / "citation-types"
    / "citation-type-meta.ts"
)


class ParsedType(NamedTuple):
    locator_kind: str
    child_skips_locator: bool
    slug_addressed: bool
    authored_root_creation: bool


def _parse_flags(source: str) -> dict[str, ParsedType]:
    """`{citation_type: ParsedType}` parsed from the TS source.

    Quote-agnostic so the parser reads both forms of the artifact: the raw
    emitter output is double-quoted JSON (`"key": "copy"`), while the committed
    file has been through prettier (`key: 'copy'`).
    """
    return {
        key: ParsedType(kind, skips == "true", slugged == "true", rooted == "true")
        for key, kind, skips, slugged, rooted in re.findall(
            r"""["']?key["']?:\s*["'](\w+)["'],.*?"""
            r"""["']?locatorKind["']?:\s*["'](\w+)["'],.*?"""
            r"""["']?childSkipsLocator["']?:\s*(true|false),.*?"""
            r"""["']?slugAddressed["']?:\s*(true|false),.*?"""
            r"""["']?authoredRootCreation["']?:\s*(true|false)""",
            source,
            re.DOTALL,
        )
    }


def _expected_flags() -> dict[str, ParsedType]:
    return {
        str(spec.source_type.value): ParsedType(
            spec.locator.kind,
            spec.child_skips_locator,
            spec.slug_addressed,
            spec.authored_root_creation,
        )
        for spec in CITATION_TYPE_SPECS.values()
    }


def test_committed_artifact_is_not_stale() -> None:
    """The committed file must already reflect the type registry — `make codegen`
    is local-only, so a forgotten regeneration would otherwise reach the frontend."""
    assert COMMITTED_META.exists(), f"{COMMITTED_META} is missing — run `make codegen`."
    actual = _parse_flags(COMMITTED_META.read_text())
    expected = _expected_flags()
    assert actual == expected, (
        "citation-type-meta.ts is stale or hand-edited — run `make codegen`. "
        f"committed={json.dumps({k: v._asdict() for k, v in actual.items()}, sort_keys=True)} "
        f"expected={json.dumps({k: v._asdict() for k, v in expected.items()}, sort_keys=True)}"
    )


def test_committed_key_union_is_not_stale() -> None:
    """CitationTypeKey is what the hand-written per-type modules assert
    exhaustiveness against, so a stale union silently drops a type's UX."""
    match = re.search(
        r"export type CitationTypeKey = ([^;]+);", COMMITTED_META.read_text()
    )
    assert match, "CitationTypeKey union not found"
    emitted = set(re.findall(r"""["'](\w+)["']""", match.group(1)))
    assert emitted == set(_expected_flags()), (
        "citation-type-meta.ts CitationTypeKey is stale — run `make codegen`."
    )
