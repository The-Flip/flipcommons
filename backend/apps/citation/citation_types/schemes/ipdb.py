"""The IPDB scheme: machine records on ipdb.org, keyed by numeric id."""

import re
from typing import Final

from apps.citation.citation_types.base import (
    SchemeRootCitationSourceInfo,
    SchemeSpec,
    SourceType,
)
from apps.citation.citation_types.url_patterns import host_prefix


def _canonical_url(machine_id: str) -> str:
    """The one URL every IPDB machine-record shape collapses to."""
    return f"https://www.ipdb.org/machine.cgi?id={machine_id}"


IPDB: Final[SchemeSpec] = SchemeSpec(
    key="ipdb",
    label="IPDB",
    source_type=SourceType.WEB,
    url_pattern=re.compile(host_prefix("ipdb.org") + r"/machine\.cgi\?id=(\d+)"),
    id_pattern=re.compile(r"\d+"),
    canonical_url=_canonical_url,
    root_citation_source_info=SchemeRootCitationSourceInfo(
        # Mirrors the root as it actually shipped in the seed data — the
        # ingest conformance check holds patch declarations to these facts.
        name="Internet Pinball Database (IPDB)",
        homepage_url="https://www.ipdb.org/",
        recognition_hosts=("ipdb.org",),
    ),
)
