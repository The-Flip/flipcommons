"""The IPDB scheme: machine records on ipdb.org, keyed by numeric id."""

import re
from typing import Final

from apps.citation.citation_types.base import RootSeed, SchemeSpec, SourceType


def _canonical_url(machine_id: str) -> str:
    """The one URL every IPDB machine-record shape collapses to."""
    return f"https://www.ipdb.org/machine.cgi?id={machine_id}"


IPDB: Final[SchemeSpec] = SchemeSpec(
    key="ipdb",
    label="IPDB",
    source_type=SourceType.WEB,
    url_pattern=re.compile(r"https?://(?:www\.)?ipdb\.org/machine\.cgi\?id=(\d+)"),
    id_pattern=re.compile(r"\d+"),
    canonical_url=_canonical_url,
    example_identifier="4443",
    root_seed=RootSeed(
        # Mirrors the root as it actually shipped in the seed data — the
        # ingest conformance check holds patch declarations to these facts.
        name="Internet Pinball Database (IPDB)",
        homepage_url="https://www.ipdb.org/",
        recognition_hosts=("ipdb.org",),
    ),
)
