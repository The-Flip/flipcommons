# Durable IDs

We keep running into cases where we wish we had a stable short durable random ID for each record: models, titles, manufacturers, people, every catalog record if not every record in the system.

## Use cases

This is needed for cross-system references.

### Pinexplore

The current case is the Pinexplore web cache: I'm trying to relate its fetched documents to models and manufacturers and systems in a stable way. Slugs can and do change. Database PKs are different machine to machine.

### Export API

Consumers of our Export API would enjoy this. They have to join `/api/public/filter/models/` results against their _saved_ copy of the export.

## URLs

### No change to canonical URL

We will NOT change our canonical URLs to `/models/abcxyz/pokemon-premium` from its current `/models/pokemon-premium`:

It _might_ help in some ways:

- We haven't yet built redirect-on-slug-change, this would obviate doing so.
- If we do this, should we relax slug uniqueness? What would be the drawbacks? Or should we not store slugs at all, but instead autogenerate slugs from the name when we display the URL?
- I bet this makes slug edit simpler.

... however, the showstopper con: `/titles/medieval-madness` is a great URL for a citable reference site — human-typeable, quotable in a forum post. `/titles/kbtqmrfz/medieval-madness` trades that away permanently to solve a problem a `301` redirect can solve.

Also, URL stability has a cheaper fix we already have the data for: superseded slug claims are the rename ledger. `test_fk_claim_pk_migration.py` already resolves stale slugs through them. A `301` from that ledger fixes renames without touching URLs at all.

### Bare ID permalink

It could be useful to have a bare-ID permalink that 301s to canonical. `/id/kbtqmrfz` → `/titles/medieval-madness`, any entity type. The link never breaks for citations, emails and pinexplore rows, without impacting the URLs people actually read and type. It 404's for any entity that doesn't have a public web route.

Reserve the ID grammar against slug collisions — there's precedent in `0030_reserve_unclassified_slug.py`.

## Scope

The entities that would get this ID:

- Yes
  - All `LinkableModel` entities (aka all of the catalog)
  - `CitationSource`
  - `User`
  - `ChangeSet` & `IngestRun`
  - `CitationInstance` already has this ID; it's the prototype. No change to it.
  - `Claim`
- No
  - `MediaAsset`/`MediaRendition` already carry uuid

## ID is globally unique across entities

The ID pool would be unique across all entities, including the existing Citation Instance IDs, including entities that don't currently have a public web route.

Having a global ID would support [bare ID permalinks](#bare-id-permalink) that resolves without knowing its type.

To be unique across entities we'd need some sort of `(durable_id, entity_type)` index table whose unique PK enforces the pool and answers `/id/<x>`.

## Where IDs get minted

Prod mints, the export publishes. IDs only need to agree between prod and downstream consumers. Dev DBs are a PII-redacted snapshot of prod. Any records created on dev machines by clicking around or by data patches are throwaway, eventually overwritten by a fresh dump from prod.

Data patches _might_ need to mint these IDs if we need to create a slugless record and then consume it a subsequent patch. But for records that have a slug, we prefer slug. Not for v1.

## Merges

When duplicate manufacturers get merged, the loser's ID should keep resolving. Soft-delete means the row survives, so merged_into + the redirect route covers it. Cheap if designed in, awkward if retrofitted.

## IDs are not claims-controlled

These IDs are system-generated, not claims-based. They never show up in the edit UI or patch field assertions (other than potentially a create-time header, and that would NOT be a claim).

## ID format

Reuse the existing Citation Instance format grammar. Its 8-char consonant-only alphabet (`models.py:805`) means vowel-free means a public URL can't accidentally spell something, and digit-free means an ID can never be confused with a PK during migration.

Collisions on mint will happen. Retries are normal and handled. We have less than 300k rows now. At 5M rows it's ~331 retries out of 5M mints, still fine.

Hoist `generate_citation_slug` to apps/core as a shared primitive — that's the model-driven move `CLAUDE.md` pushes.

## Name of ID field

Let's use `durable_id`.

- ✅ `durable_id`: slightly better than `stable_id`
- `stable_id`
- ❌ `flip_id`: the Flipcommons ID. No good if we rebrand.
- ❌ `short_id`: no good if we have to turn it into a GUID later
- ❌ `global_id`: global implies world-unique like a UUID; this is unique within one system

## Abstract base class

I assume we'd have an abstract base class that adds the ID to each model.

## Analytics

We'd add this ID into the analytics foundation.

Does some of the analytics foundation gets simpler with everything having a global ID?

## MVP

Add to the Yes entities, minted at create.
Backfill.
Support in analytics, in the export API.
Everything else is optional follow-up: bare ID URL, merges, etc.
