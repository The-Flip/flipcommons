"""Input shapes for the data-patch ``sources:`` block.

The deserialized, pre-DB representation of a citation source declared in a patch:
``SourceNode`` mirrors a ``CitationSource`` row and ``SourceLinkNode`` a
``CitationSourceLink``. The patch parser narrows raw JSON to these, and
``source_upsert`` consumes them to get-or-create the rows.
"""

from __future__ import annotations

from typing import NotRequired, TypedDict


class SourceLinkNode(TypedDict):
    url: str
    link_type: str
    label: NotRequired[str]


class SourceNode(TypedDict):
    name: str
    source_type: str
    author: NotRequired[str]
    publisher: NotRequired[str]
    year: NotRequired[int]
    month: NotRequired[int]
    day: NotRequired[int]
    date_note: NotRequired[str]
    isbn: NotRequired[str]
    description: NotRequired[str]
    identifier_key: NotRequired[str]
    domains: NotRequired[list[str]]
    links: NotRequired[list[SourceLinkNode]]
    children: NotRequired[list[SourceNode]]
