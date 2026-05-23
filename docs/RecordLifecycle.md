# Record Lifecycle

This document describes the catalog record lifecycle: the data-model policy for
creating, deleting, restoring, and duplicate-checking catalog records.

This lifecycle applies to every write path, including user actions, ingest, admin
tools, and other API clients.

## Creation

Catalog records enter the system through multiple channels, such as user
actions, ingest, admin tools, and other API clients. Every path produces the
same kind of record. Each claim still carries its source through its
`ChangeSet` or ingest run, and source views surface that provenance, but the
record itself is not flagged or typed by where it came from.

Records are published immediately once created. User and API-client creates
write a `ChangeSet` with action `create`; ingest creates write an ingest
`ChangeSet` identified by its `ingest_run` FK. In both cases the resulting
claims appear in edit history and source views like any other claim.

Interactive create flows should ask for the minimum fields needed to make a
valid record, usually name plus slug and any required parent or owner reference.
Optional catalog detail belongs in the normal edit flow after creation. Newly
created records should be findable immediately in lists, search, and selection
controls. Create screens may include optional notes and citations using the
same mechanisms as edit screens; neither is required.

## Deletion

Catalog records are soft-deleted. Deletion writes a `status = deleted` claim
inside a `ChangeSet` with action `delete`; it does not remove the database row.
The catalog record lifecycle has no hard delete operation.

Independent lifecycle-managed catalog entities are the records that can be
meaningfully deleted. Owned child rows without their own lifecycle status, such
as aliases, credits, many-to-many through rows, and provenance bookkeeping,
ride with the parent record's visibility rather than receiving fake lifecycle
claims.

Read APIs currently treat soft-deleted records as not found.

## Cascade Rules

Soft-delete behavior mirrors database foreign-key semantics, but it must account
for resolved lifecycle status:

| Relationship shape                                              | Soft-delete behavior                                                         |
| --------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `PROTECT`, referenced by an active independent lifecycle entity | Block the delete and report the active referrer.                             |
| `PROTECT`, referenced only by soft-deleted lifecycle entities   | Allow the delete; soft-deleted referrers do not count as active blockers.    |
| `CASCADE` to an independent lifecycle entity                    | Write `status = deleted` claims for active children in the same `ChangeSet`. |
| `CASCADE` to an owned child row without lifecycle status        | Do nothing special; the child disappears with the parent.                    |

A record counts as active when its resolved `status` claim is anything other
than `deleted`. Database-level `PROTECT` constraints operate on raw rows and
cannot see `status = deleted`. Application code must therefore compute active
blockers by walking relationships and filtering by resolved status. Database
constraints remain a safety net against accidental hard deletes.

A cascading delete counts as one delete action and one `ChangeSet`, even when it
writes claims for many records.

## Restore And Undo

Undo and restore are distinct operations:

- **Undo** inverts a specific delete `ChangeSet`. If the delete cascaded to child
  records, undo restores the whole tree because the original `ChangeSet` contains
  every child `status = deleted` claim.
- **Restore** writes a fresh `status = active` claim for one record. It does not
  automatically restore children deleted by an earlier cascading delete.

Undo is available only while the delete `ChangeSet` is still the latest action
against the relevant record. Restore is the mechanism for records whose delete is
older or has been superseded. Undo writes a `ChangeSet` with action `revert`;
restore writes one with action `create`, since it brings a record back into
existence with a fresh active claim.

## Duplicate Prevention

Duplicate prevention is an API invariant, not just a UI affordance. The UI
should make users look before creating, but create endpoints must reject
collisions even when a request bypasses the UI or races another writer. Ingest
follows the same invariant: it must resolve to an existing record or create a
new one, never produce a duplicate.

Slug uniqueness is database-enforced where routing requires it. Name and alias
collisions are application-enforced when normalized-name semantics are needed.
Aliases count as alternate names for duplicate-prevention purposes.

For large lists, creation should be offered after search returns no results. For
small lists where the whole set is visible, a create link in the list header is
enough. Both paths rely on the same API-level collision checks.

## Rate Limits

Rate-limit values live in `backend/apps/provenance/constants.py`; change them
there. Limits are rolling-window, per-user, and apply to user-driven
`ChangeSet`s. Ingest is not rate-limited, staff accounts are exempt through the
rate-limit policy, and a cascading delete counts as one delete action.

Each route's activity classification determines which bucket the request
charges: `CATALOG_CREATE` → create, `CATALOG_EDIT` → edit, `CATALOG_DELETE` →
delete. Create, edit and delete each have their own rolling window. Restore is
classified as `CATALOG_CREATE` because it reintroduces a record, even though
the underlying `ChangeSet` carries `action=EDIT`. Undo does not consume any
bucket — reverting a recent mistake should not cost the user a slot.
