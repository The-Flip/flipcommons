"""The parked source fields the provenance pages hide.

A claim whose ``field_name`` matches neither a claim-controlled column nor a
relationship namespace is *parked*: resolution drops it into the entity's
``extra_data`` JSON instead of a column. Parked claims are ingest-only — no
editable field set exposes one, so no user can author one — and they carry a
source's own bookkeeping (raw IPDB note text, OPDB image blobs) rather than
catalog facts. Provenance is about who claimed what, so it leaves them out.

Named explicitly rather than derived from the structural rule ("no column, no
namespace") because the set is closed: every parked claim in the database was
written by the one bootstrap ingest, and no data patch has produced one since.
That makes the drift risk small and inverts it usefully — a patch that parks a
*new* field surfaces unhidden, which is a data problem worth seeing rather than
one worth suppressing automatically.

Only the claim rows are hidden; ``extra_data`` itself is untouched and still
ships whole.
"""

from __future__ import annotations

from apps.core.types import ClaimFieldName

__all__ = ["HIDDEN_PARKED_FIELDS"]


HIDDEN_PARKED_FIELDS: frozenset[ClaimFieldName] = frozenset(
    {
        "image_urls",
        "ipdb.corporate_entity_name",
        "ipdb.image_urls",
        "ipdb.manufacturer_trade_name",
        "ipdb.marketing_slogans",
        "ipdb.notable_features",
        "ipdb.notes",
        "ipdb.toys",
        "opdb.common_name",
        "opdb.description",
        "opdb.features",
        "opdb.images",
        "opdb.keywords",
    }
)
