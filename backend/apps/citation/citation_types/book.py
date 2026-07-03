"""The book citation type: a standalone authored work.

A parentless book is the work itself — citable directly — and may nest
editions beneath it. Locators are freeform (page, chapter).
"""

from apps.citation.citation_types.base import CitationTypeSpec, SourceType

BOOK = CitationTypeSpec(
    source_type=SourceType.BOOK,
    flat_hierarchy=False,
    parentless_abstract=False,
    child_skips_locator=False,
)
