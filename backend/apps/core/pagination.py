"""Pagination subclass that names its OpenAPI input and output components.

Ninja's ``PageNumberPagination`` registers two OpenAPI components from
inner classes: ``Input`` (query params) and the response wrapper, which is
constructed dynamically as ``Paged{ItemSchemaName}``. Both names are
problematic at the component level — ``Input`` is too generic, and
``Paged{ItemListItemSchema}`` mixes the wrapper "Paged" prefix with the
row "ListItem" suffix.

This module fixes both:

- ``NamedPageNumberPagination.Input`` is overridden with an inner Schema
  named ``PaginationParamsSchema`` so the input component is registered
  under that name.
- ``NamedPageNumberPagination.Output`` is overridden with
  ``NamedPaginatedResponseSchema``. ``ninja.pagination.make_response_paginated``
  is monkey-patched to honor a ``response_name`` class attribute on the
  paginator subclass; when set, the dynamic wrapper class is named
  accordingly instead of ``Paged{ItemSchemaName}``.

The patch is opt-in (only triggers when ``response_name`` is set), so any
paginator that doesn't define ``response_name`` keeps Ninja's default
behavior.
"""

from __future__ import annotations

from typing import Any, ClassVar

import ninja.pagination as _ninja_pagination
from ninja import Field, Schema
from ninja.operation import Operation
from ninja.pagination import PageNumberPagination, PaginationBase


class NamedPaginatedResponseSchema(Schema):
    items: list[Any] = Field(..., description="The page of items.")
    count: int = Field(..., description="Total items count.")


class NamedPageNumberPagination(PageNumberPagination):
    class PaginationParamsSchema(Schema):
        page: int = Field(1, ge=1, description="Page number, 1-based.")
        page_size: int | None = Field(
            None,
            ge=1,
            description="Items per page. Defaults to the server's page size.",
        )

    Input = PaginationParamsSchema  # type: ignore[assignment]
    Output = NamedPaginatedResponseSchema  # type: ignore[assignment]
    response_name: ClassVar[str | None] = None


_orig_make_response_paginated = _ninja_pagination.make_response_paginated


def _make_response_paginated(paginator: PaginationBase, op: Operation) -> None:
    name = getattr(paginator, "response_name", None)
    if not name:
        _orig_make_response_paginated(paginator, op)
        return
    status_code, item_schema = _ninja_pagination._find_collection_response(op)
    new_schema = type(
        name,
        (paginator.Output,),
        {"__annotations__": {paginator.items_attribute: list[item_schema]}},  # type: ignore[valid-type]
    )
    response = op._create_response_model(new_schema)
    op.response_models[status_code] = response


_ninja_pagination.make_response_paginated = _make_response_paginated
