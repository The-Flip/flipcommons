"""The document citation type: publisher roots with discrete published documents.

A discrete published document, addressed by publisher plus slug — a
manufacturer's operations manual or schematic, a patent under its issuing
office. A parentless document is always the **publisher** (Williams, USPTO) —
abstract, a container, never cited directly; the citable evidence is a child
(``williams:wpc-95-schematic-manual``, ``uspto:us4373731``). Roots are not
authored interactively: publisher roots arrive from data patches, so the
create flow only ever adds documents under an existing publisher. Locators
are freeform (page, section, sheet).
"""

from apps.citation.citation_types.citation_type_specs import CitationTypeSpec
from apps.citation.citation_types.vocabulary import SourceType

DOCUMENT = CitationTypeSpec(
    source_type=SourceType.DOCUMENT,
    flat_hierarchy=False,
    schemeless_parentless_abstract=True,
    child_skips_locator=False,
    slug_addressed=True,
    child_noun_plural="documents",
    authored_root_creation=False,
)
