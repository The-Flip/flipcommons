"""The periodical citation type: a publication container with issues/articles.

A magazine, newspaper, trade journal or newsletter — one type, because they
do not differ in behavior. A parentless periodical is a publication —
abstract, cite a child instead. Locators are freeform (page, column,
section).
"""

from apps.citation.citation_types.citation_type_specs import CitationTypeSpec
from apps.citation.citation_types.vocabulary import SourceType

PERIODICAL = CitationTypeSpec(
    source_type=SourceType.PERIODICAL,
    flat_hierarchy=False,
    schemeless_parentless_abstract=True,
    child_skips_locator=False,
    slug_addressed=True,
    child_noun_plural="issues",
    authored_root_creation=True,
)
