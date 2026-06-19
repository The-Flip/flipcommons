"""The private internal entity HTTP-surface registrars.

Generic create / detail / listing / delete-restore machinery over any
``LinkableClaimModel``, split by operation into the sibling subpackages
(:mod:`.create`, :mod:`.detail`, :mod:`.listing`, :mod:`.delete`). Catalog's
per-entity routers mount these, injecting per-entity querysets, serializers and
hooks. Each subpackage is the public API for its operation family.
"""
