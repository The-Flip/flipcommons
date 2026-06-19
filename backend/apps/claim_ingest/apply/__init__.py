"""Apply engine: source-agnostic execution of an :class:`IngestPlan`.

Processes three explicit primitives — ``create_entity``, ``assert_claim``,
``retract_claim`` — in one transaction.  Contains no source-specific logic; every
adapter (IPDB, OPDB, the data-patch system …) compiles its input into an
``IngestPlan`` (see :mod:`apps.claim_ingest.plan`) and calls
:func:`apply_plan`.

Design decisions that look like bugs but aren't:

- ``IngestRun`` is created **outside** the transaction so it survives
  rollback.  A failed run is exactly when you most want the audit record.
- Structural plan errors (bad handles, missing assertions) raise
  **before** ``IngestRun`` creation — they're adapter bugs, not data
  issues, and shouldn't leave audit debris.
- Validation is fail-fast but **exhaustive**: all invalid claims are
  collected before raising, so one run surfaces every data quality issue.

Split by pipeline stage, dependencies flowing one way (leaves → composers):

- :mod:`.validate` — structural plan integrity checks (LEAF).
- :mod:`.claims` — build → validate-values → diff claims, shared by both
  paths; owns ``RetractEntry`` (LEAF).
- :mod:`.dry_run` — read-only validate + diff; depends on ``claims``.
- :mod:`.persist` — entity creation, citation minting and the claim/ChangeSet
  writes; depends on ``claims``. Holds the only two catalog touchpoints.
- :mod:`.orchestrate` — ``apply_plan``: transaction structure + run bookkeeping.

The public surface is :func:`apply_plan`; callers import it from this package
regardless of which stage module a helper lives in.
"""

from __future__ import annotations

from apps.claim_ingest.apply.orchestrate import apply_plan

__all__ = ["apply_plan"]
