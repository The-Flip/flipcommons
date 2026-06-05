from typing import Annotated

from ninja.params.functions import Query as QueryParam

DEFAULT_PAGE_SIZE = 50

# ---------------------------------------------------------------------------
# Reusable documented query params for the public list endpoints.
#
# ``ninja.Query`` is the generic ``Annotated[T, ...]`` alias used for the
# schema-as-query form (``Query[FooFilterSchema]``); calling it as ``Query(...)``
# trips mypy. ``ninja.params.functions.Query`` is the underlying param function
# (returns ``Any``), so it's the mypy-clean way to attach a ``description`` to a
# bare handler argument via ``Annotated``. These aliases bake in the wording so
# the per-endpoint docs can't drift.
# ---------------------------------------------------------------------------

_Q_NAME_DESC = "Free-text search by name. Accent- and case-insensitive substring match."
_Q_NAME_ALIAS_DESC = (
    "Free-text search by name or alias. Accent- and case-insensitive substring match."
)
_PAGE_DESC = "Page number, 1-based."

# ``q`` for entities matched by name only.
NameQuery = Annotated[str, QueryParam("", description=_Q_NAME_DESC)]
# ``q`` for entities that also match on their aliases.
NameAliasQuery = Annotated[str, QueryParam("", description=_Q_NAME_ALIAS_DESC)]
# Standard 1-based ``page`` param.
PageParam = Annotated[int, QueryParam(1, description=_PAGE_DESC)]
