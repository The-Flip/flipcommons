"""The magazine citation type: a publication container with issues/articles.

A parentless magazine is a publication — abstract, cite a child instead.
Locators are freeform (page, column).
"""

from apps.citation.citation_types.citation_type_specs import CitationTypeSpec
from apps.citation.citation_types.vocabulary import SourceType

MAGAZINE = CitationTypeSpec(
    source_type=SourceType.MAGAZINE,
    flat_hierarchy=False,
    parentless_abstract=True,
    child_skips_locator=False,
)
