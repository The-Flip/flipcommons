"""``WikilinkableModel`` — the abstract base catalog models inherit to
appear in the wikilink autocomplete picker.

Inheriting opts a model into the ``[[<entity-type>:<public-id>]]`` autocomplete picker
surfaced by the markdown editor. Models that are URL-addressable but
should not appear in the picker (e.g. Location) inherit
:class:`apps.core.models.LinkableModel` only, not this base.

The class carries only the picker's *menu* presentation
(label / description / sort order). The *search* behavior comes from
:class:`apps.core.autocomplete.AutocompletableModel` (its second base) and the
:func:`apps.core.autocomplete.run_autocomplete` engine.
"""

from __future__ import annotations

from typing import ClassVar

from apps.core.autocomplete import AutocompletableModel
from apps.core.models import LinkableModel


class WikilinkableModel(LinkableModel, AutocompletableModel):
    """A :class:`LinkableModel` that opts into the wikilink picker.

    Composes link addressability (``LinkableModel``) with autocomplete
    searchability (:class:`AutocompletableModel`).

    ``link_label`` / ``link_description`` carry the empty-string sentinel as
    their declared default; the registration loop in
    :meth:`apps.catalog.apps.CatalogConfig._register_picker_types`
    materializes the real fallbacks from ``model._meta.verbose_name`` at
    app-ready time, when Django's ``_meta`` is fully wired (it is not yet
    wired during ``__init_subclass__``).
    """

    link_sort_order: ClassVar[int] = 100
    link_label: ClassVar[str] = ""
    link_description: ClassVar[str] = ""

    class Meta:
        abstract = True
