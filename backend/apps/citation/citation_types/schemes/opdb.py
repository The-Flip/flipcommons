"""The OPDB scheme: machine records on opdb.org, keyed by slug id."""

import re

from apps.citation.citation_types.base import RootSeed, SchemeSpec, SourceType

OPDB = SchemeSpec(
    key="opdb",
    label="OPDB",
    source_type=SourceType.WEB,
    url_pattern=re.compile(r"https?://(?:www\.)?opdb\.org/machines/([A-Za-z0-9_-]+)"),
    id_pattern=re.compile(r"[A-Za-z0-9_-]+"),
    canonical_url=lambda id: f"https://opdb.org/machines/{id}",
    example_identifier="GRhX5",
    root_seed=RootSeed(
        name="OPDB",
        homepage_url="https://opdb.org/",
        recognition_hosts=("opdb.org",),
    ),
)
