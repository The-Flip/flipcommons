"""The book citation type: a standalone authored work.

A parentless book is the work itself — citable directly — and may nest
editions beneath it. Locators are freeform (page, chapter).
"""

from apps.citation.citation_types.citation_type_specs import CitationTypeSpec
from apps.citation.citation_types.vocabulary import SourceType

BOOK = CitationTypeSpec(
    source_type=SourceType.BOOK,
    flat_hierarchy=False,
    schemeless_parentless_abstract=False,
    child_skips_locator=False,
    slug_addressed=False,
    child_noun_plural="editions",
    authored_root_creation=True,
)
