# ChangeSet

## Status: ✅ DONE

This plan has been implemented.

## Background

This project's catalog data is built on a claims/provenance system: every field value is a **Claim** asserted by either an automated Source (IPDB, OPDB, etc.) or a human User. Claim resolution picks the winning value per field based on source priority, with most-recent as a tiebreaker.

What was missing was a way to **group related claims** into a single logical edit. When a user updates a GameplayFeature's description and rearranges its parent hierarchy in one form submission, those changes are conceptually one action — but without grouping, each claim is an independent record with no link to the others.

The ChangeSet model fills this gap. It's inspired by Wikidata's edit model (where `wbeditentity` bundles multiple field changes into one revision) and OpenStreetMap's changeset concept (which groups element changes from one editing session).

## What a ChangeSet is

A ChangeSet is a **thin grouping record** that links claims made together in a single edit session. It carries:

- A **user** (FK to the actor, nullable — for future source-level ChangeSets)
- A **note** (optional free text explaining the edit)
- A **timestamp** (when the edit was submitted)

Claims link to a ChangeSet via an optional foreign key. The ChangeSet itself does not carry author or subject information — the individual Claims already have that (each Claim has a `user` or `source` FK, and a GenericFK to the entity it targets).

**Single-actor invariant:** All claims in a ChangeSet must share the same actor (same user or same source). This is enforced in the code that creates ChangeSets, not by a FK on ChangeSet itself. A ChangeSet with mixed actors would not be a coherent unit for audit, revert, or review.

## What a ChangeSet is NOT

- **Not a snapshot.** It does not store entity state before or after the edit. Truth is always derived from claim resolution (highest priority wins). There is no "revert to version N" by restoring a snapshot — reverting means creating inverse claims.

- **Not scoped to one entity.** A user edit session typically targets one entity, but the model doesn't enforce this. This keeps it flexible for future use by ingest runs, which touch many entities in one execution.

- **Not the canonical author record.** The ChangeSet carries a `user` FK for convenient querying ("show all edits by user X"), but Claims remain the authoritative source of attribution via their own user-XOR-source constraint. The ChangeSet user FK is denormalization — always consistent because the same code sets both atomically.

## Use cases

### User editing (immediate)

A user opens the GameplayFeature edit page, changes the description, adds a parent, and writes a note: "Added drop targets as a parent category." On submit, the backend creates one ChangeSet with the note, then creates Claims for each changed field linked to that ChangeSet. The activity view groups these claims by ChangeSet and displays the note.

### Ingest run tracking (future, needs design)

An IPDB ingest fetches updated data and creates/updates claims across hundreds of entities. Tracking what changed per run is valuable, but a single ChangeSet per ingest run is the wrong granularity — it would be too coarse for revert, review, or activity display. An ingest run is a higher-level concept (e.g., `IngestRun` or `ImportBatch`) that would either contain multiple ChangeSets or operate independently. This needs its own design work when we get there.

### Audit and history (future)

The activity tab already shows individual claims. With ChangeSets, the UI can group claims by edit session: "User @dean changed description and parents on Mar 25" with the edit note visible. This is more useful than a flat list of individual claim changes.

### Revert (future, needs design)

The general principle is clear: reverting creates inverse claims, never deletes history, and the revert itself is a new ChangeSet. But the details are an open design problem. Key questions include: what happens when claims from the target ChangeSet are no longer the current winners (interleaved edits)? Should revert restore historical predecessors or compensate against current state? How do relationship claims (add/remove parents) interact with revert? These need to be worked out when we're closer to building it.

### Review workflow (future, needs design)

When we add a review queue for less-trusted users, a ChangeSet is the natural unit of review — a curator approves or rejects the entire edit, not individual claims. However, a status flag on ChangeSet alone is not sufficient. Current claim resolution filters on `claim.is_active` and `source.is_enabled`, not ChangeSet status. Pending edits would need to either be created with `is_active=False` (activated on approval) or live in a separate proposal layer outside the claims table. This requires deeper integration with the resolution system and needs its own design.

## Key decisions

| Decision                | Choice                                 | Rationale                                                                                                                                                |
| ----------------------- | -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Grouping model          | Thin changeset, not snapshot           | Truth lives in claims + resolution. Snapshots would duplicate the source of truth.                                                                       |
| Subject FK on ChangeSet | No                                     | Claims carry their own subject. Dropping it keeps the model flexible for multi-entity ingest runs.                                                       |
| User FK on ChangeSet    | Yes (nullable)                         | Useful denormalization for "show edits by user X" queries. Consistency risk is low — set atomically with claims. Source FK deferred until ingest design. |
| Note location           | On ChangeSet, not on individual Claims | One note per edit session. Claims already have a `citation` field for per-claim source info.                                                             |
| Revert semantics        | Create inverse claims                  | Never delete history. A revert is itself a new ChangeSet.                                                                                                |
| Name                    | ChangeSet, not Revision                | "Revision" implies a snapshot/version in wiki systems. ChangeSet says what it is: a set of changes.                                                      |
