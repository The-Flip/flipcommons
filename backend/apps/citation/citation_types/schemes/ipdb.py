"""The IPDB scheme: machine records on ipdb.org, keyed by numeric id."""

import re
from typing import Final

from apps.citation.citation_types.base import (
    SchemeRootCitationSourceInfo,
    SchemeSpec,
    SourceType,
)
from apps.citation.citation_types.url_patterns import QUERY_ID_BOUNDARY, host_prefix

IPDB: Final[SchemeSpec] = SchemeSpec(
    key="ipdb",
    label="IPDB",
    source_type=SourceType.WEB,
    url_pattern=re.compile(
        host_prefix("ipdb.org") + r"/machine\.cgi\?id=(\d+)" + QUERY_ID_BOUNDARY
    ),
    id_pattern=re.compile(r"\d+"),
    canonical_url_template="https://www.ipdb.org/machine.cgi?id={identifier}",
    root_citation_source_info=SchemeRootCitationSourceInfo(
        # Mirrors the root as it actually shipped in the seed data — the
        # ingest conformance check holds patch declarations to these facts.
        name="Internet Pinball Database (IPDB)",
        homepage_url="https://www.ipdb.org/",
        recognition_hosts=("ipdb.org",),
    ),
)
