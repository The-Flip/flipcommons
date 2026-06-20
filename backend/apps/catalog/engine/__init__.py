"""Domain-neutral engine: the generic HTTP surface over any ``LinkableClaimModel``.

The reusable, pinball-agnostic core that catalog's per-entity routers mount and
the concrete domain models subclass — drawn as an in-app boundary today,
enforced by the ``Engine does not import the catalog domain`` import-linter
contract, so lifting it to its own top-level app at domain-swap time is a
``git mv``.

Layout:

- :mod:`.entity_api` — the private internal API registrars (create / detail /
  listing / delete-restore), each operation family its own subpackage.
- :mod:`.query` — generic list-query fold + facet leaves.
- :mod:`.schemas` — cross-cutting wire bases (``EntityRef``, the detail bases…).
- :mod:`.models` — the one generic catalog-level model base (``AliasModel``).
- :mod:`.aliases` / :mod:`.naming` / :mod:`.walks` — generic substrate.

The public API is the subpackages, imported directly (e.g.
``from ...engine.entity_api.create import register_entity_create``). This
``__init__`` deliberately stays import-light: it is loaded during Django model
setup (``catalog.models.base`` imports ``engine.models``), so eagerly importing
the registrars here — which pull in ``claim_edit`` and the ninja routers — would
risk an import cycle before the app registry is ready.
"""
