"""The web citation type: site roots with page children.

A parentless web source is a site — abstract, never cited directly;
recognition resolves a URL to a page child under the matched root. Web
children skip the locator stage: their URL *is* the locator.
"""

from apps.citation.citation_types.base import CitationTypeSpec, SourceType

WEB = CitationTypeSpec(
    source_type=SourceType.WEB,
    flat_hierarchy=True,
    parentless_abstract=True,
    child_skips_locator=True,
)
