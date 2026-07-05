"""The IPDB scheme: machine records on ipdb.org, keyed by numeric id."""

from typing import Final

from apps.citation.citation_types.citation_scheme_specs import (
    SchemeRootCitationSourceInfo,
    SchemeSpec,
    UrlShape,
)
from apps.citation.citation_types.vocabulary import SourceType

SCHEME: Final[SchemeSpec] = SchemeSpec(
    key="ipdb",
    label="IPDB",
    source_type=SourceType.WEB,
    url_shapes=(
        UrlShape(hosts=("ipdb.org",), path=r"/machine\.cgi", query_id_param="id"),
    ),
    id_pattern=r"\d+",
    canonical_url_template="https://www.ipdb.org/machine.cgi?id={identifier}",
    root_citation_source_info=SchemeRootCitationSourceInfo(
        # Mirrors the root as it actually shipped in the seed data — the
        # ingest conformance check holds patch declarations to these facts.
        name="Internet Pinball Database (IPDB)",
        homepage_url="https://www.ipdb.org/",
        recognition_hosts=("ipdb.org",),
    ),
)
