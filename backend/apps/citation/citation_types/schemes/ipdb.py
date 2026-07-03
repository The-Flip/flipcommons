"""The IPDB scheme: machine records on ipdb.org, keyed by numeric id."""

import re

from apps.citation.citation_types.base import RootSeed, SchemeSpec, SourceType

IPDB = SchemeSpec(
    key="ipdb",
    label="IPDB",
    source_type=SourceType.WEB,
    url_pattern=re.compile(r"https?://(?:www\.)?ipdb\.org/machine\.cgi\?id=(\d+)"),
    id_pattern=re.compile(r"\d+"),
    canonical_url=lambda id: f"https://www.ipdb.org/machine.cgi?id={id}",
    example_identifier="4443",
    root_seed=RootSeed(
        name="IPDB",
        homepage_url="https://www.ipdb.org/",
        recognition_hosts=("ipdb.org",),
    ),
)
