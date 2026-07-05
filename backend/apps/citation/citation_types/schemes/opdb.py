"""The OPDB scheme: machine records on opdb.org, keyed by slug id."""

from typing import Final

from apps.citation.citation_types.citation_scheme_specs import (
    SchemeRootCitationSourceInfo,
    SchemeSpec,
    UrlShape,
)
from apps.citation.citation_types.vocabulary import SourceType

OPDB: Final[SchemeSpec] = SchemeSpec(
    key="opdb",
    label="OPDB",
    source_type=SourceType.WEB,
    url_shapes=(UrlShape(hosts=("opdb.org",), path=r"/machines/{id}"),),
    id_pattern=r"[A-Za-z0-9_-]+",
    canonical_url_template="https://opdb.org/machines/{identifier}",
    root_citation_source_info=SchemeRootCitationSourceInfo(
        # Mirrors the root as it actually shipped in the seed data — the
        # ingest conformance check holds patch declarations to these facts.
        name="Online Pinball Database (OPDB)",
        homepage_url="https://opdb.org/",
        recognition_hosts=("opdb.org",),
    ),
)
SCHEME: Final[SchemeSpec] = OPDB
