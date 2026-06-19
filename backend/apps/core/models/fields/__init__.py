"""Shared Django field classes for ``apps.core``.

Mirrors Django's own ``django.db.models.fields`` layout. The two field
classes share nothing but the length-CHECK helper, so each lives in its
own module:

- :mod:`text` — :class:`BoundedTextField`, a plain length-bounded TextField.
- :mod:`markdown` — :class:`MarkdownField`, the storage class for wikilink
  markdown content (re-exported by :mod:`apps.core.markdown`).
- :mod:`_max_length` — the shared ``char_length`` CHECK contributor.
"""

from apps.core.models.fields.markdown import (
    DEFAULT_MARKDOWN_MAX_LENGTH,
    MarkdownField,
)
from apps.core.models.fields.text import BoundedTextField

__all__ = [
    "DEFAULT_MARKDOWN_MAX_LENGTH",
    "BoundedTextField",
    "MarkdownField",
]
