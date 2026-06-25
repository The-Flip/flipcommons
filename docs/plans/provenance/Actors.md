# Actors

How to represent all the actors in the system, human and non, such as the AI agents that create [data patches](/docs/DataPatches.md).

## Types of actors

### Human users aka contributors

Authenticated via WorkOS.

### Ingest sources

Every [data patch](/docs/DataPatches.md) is currently attributed to a `source`, like `flipcommons_catalog`.

When we receive structured data from a 3rd party, such as the OPDB API, we attribute it to them via a source like `opdb`.

These sources are a separate database table from User; there's no connection between User and Source.

These sources don't currently connect to the live system; instead, they author data patches on a developer's localhost, and the developer manages the ingest. Currently, we're reviewing data patches in the IDE and Github Desktop diffs, but that's probably an artifact of the system immaturity: we keep finding things we want to change about the system as we author the patches (and often change it in order to ship a better data patch), so we're keeping a close eye on them.

### 3rd party bots

We don't support 3rd party bots / automation yet, but we aim to. This system must be AI-native.

Third party bots probably will not connect via a username/password, but something like an API key.

### 1st party bots

We don't have 1st party bots / automation yet, but we aim to have our own agents/jobs that write via API key but under our trust/ownership. Basically the next generation of the `source` concept that we currently use for data patches.

### System actor

We don't have this concept yet, but most of the prior art systems below have a way to represent the thing that owns writes with no external originator, such as derived-field recomputation, scheduled jobs, auto-moderation, status transitions, and absorbing orphaned history.

It's not yet clear where the line between a 1st party bot and a system actor is. Maybe it turns out there isn't one.

### Organization

Ability for a claim to be attributed to an organization or company, like 'The New York Times Editorial Staff' or 'Kineticist'.

That's sort of what we already do with sources like `ipdb` and `opdb` , but we'd want to support the IPDB people themselves logging in and doing things on behalf of their organization. TBD, but our ingest of OPDB might be attributed to the actual same organization record as the OPDB people logging in, even if they don't control our OPDB scraping bot (doing so would be presumptuous and rude). An etiquitte problem, not a technical problem.

### Out of scope

#### Out of scope: anonymous users

We aren't targeting guest users writing data.

#### Out of scope: subjects

Pat Lawlor, the pinball designer, is a Person record in the catalog, is a subject. That Person record is NOT an actor.

## Credentials and connection

Here's if and how an actor authenticates and connects to the live system:

| Actor         | Attributed to            | Credential        | Connects live?   | Write origin                              |
| ------------- | ------------------------ | ----------------- | ---------------- | ----------------------------------------- |
| Human user    | their `User`             | WorkOS session    | Yes              | interactive, in-app                       |
| Ingest source | the `source` like `opdb` | none              | No               | out-of-band patch, applied by a developer |
| 3rd party bot | the bot                  | API key           | Yes              | programmatic API                          |
| 1st party bot | the bot                  | API key (ours)    | Yes              | programmatic API                          |
| System actor  | the system identity      | none (in-process) | n/a              | internal: derived fields, scheduled jobs  |
| Organization  | the org                  | none directly     | only via members | delegated through a human or bot          |

The table separates three things that are easy to conflate:

- **identity**: who the actor is, the thing attribution points at
- **credential**: how it proves it may act
- **connection**: whether it touches the live system itself, or its work arrives out of band via an intermediary

The payoff is in the **credential** column: ingest sources, the system actor and organizations receive attribution without ever authenticating — so **attribution is decoupled from authentication**. The rows where the credential-holder is not the attributed actor (a developer's session writing as `opdb`; a member's session writing as their org) are exactly the delegation cases, which gives a one-line test for "this is on-behalf-of": credential-holder ≠ attributed actor.

## Goals

### Single path through the system

We already regret not rationalizing humans (User) and ingest sources because it created multiple paths through the system, and we're seeing inconsistencies because of it, like there's nowhere to see the contributions made by a source, and some things (like Citation Sources) can't be attributed to a data source.

This will only get worse as the system grows.

We want to support all these different types of actors via a single path through the system. We don't want a single `if actor_type=x` statement.

#### Single path through provenance

Currently, the provenance / attribution / claims system is forked in different places depending on whether the claim is attributed to a User or a Source. In order to simplify the system, we'd like to have a single path through attribution of claims.

For example, you can see a user's contributions at /user/[username], but you can't see an ingest source's contributions. That sort of thing shouldn't be a separate path, we should get it automatically.

#### Single path through trust & reliability weighting

Right now `User.priority` and `Source.priority` drive conflict resolution. We want to generalize it: every actor carries a trust level that feeds claim ranking. A bot ≠ a curated source ≠ a human.

#### Single path through authz

Per-actor authorization scoping. What an actor may write gated through Activity (the authz system) — a 3rd-party bot's API key has narrower scope than a human, like GitLab token scopes / K8s RBAC.

At some point we'll introduce more and less trusted contributors who are allowed more and less capabilities, such as gardening citation sources and writing claims without review. At that point we'll want a single path through the system for this for all actors.

#### Single path through rate limiting

Be able to throttle humans and machines through a single machinery.

#### Single path to deal with deleted / banned / deactivated user

When an actor is removed, how/what do we attribute their contributions? There are multiple user states:

- **Deleted**: erasure — data must go
- **Banned**: disabled, writes maybe repudiated
- **Deactivated**: voluntary, reversible, writes stay

#### Single path for licensing

Right now `Source` carries licensing info, like CC-BY-SA. Other types of bots will have similar concerns. In the future I might see a user specifying what licensing their contributions would be under. Should probably be a single path through attribution to licensing.

#### Single path for access tokens?

At some point we may want to create API keys for users, similar to GitHub Personal Access Tokens (PATs). Probably would be nice for the bot API keys and these user API keys to share the same paths for everything.

### Attribute every claim write

Currently, we do NOT attribute every claim write; ingest-minted rows can be originless.

Every claim write must be attributable to exactly one actor — no unattributed rows. No anonymous writes, ever.

This is currently not done in part because there's not a single attribution path through provenance.

### Support AI actors

AI-native programmatic contribution as a first-class write path.

### Transparency and trust

Build trust in the system by enable a reader to know with fine degrees of meaning how any particular change got made: the 'on behalf of', 'co-authored by', tell a machine edit from a human one.

### Distinguish machine vs human actors

Be able to easily distinguish between human and machine actors. Machine-vs-human is a property of the actor.

### Support 'On behalf of' (delegation)

Our ingest flow is delegation, but we currently don't represent it as such: a developer commits a patch attributed to a source.

#### 'On behalf of' an organization

Ability for an actor to do something on behalf of an organization, like Pat Klein writing a description for a new model on behalf of The Kineticist organization.

This is simply another example of delegation at work, I'd hope we get it for free.

### Support 'Assisted by' or 'Co-authored' (AI assistance)

Some way to mark that an actor's work was assisted by another actor or co-authored with another actor. This is a human directing an AI to do creation, much like Github commits can be co-authored by AI.

## Scoping

### ✅ In scope for v1

#### ✅ Human users

#### ✅ Ingest sources

#### ✅ Attribute every claim write

#### ✅ Distinguish machine vs human actors

#### ✅ Single path through provenance

#### ✅ Single path through trust & reliability weighting

#### ✅ Single path through resolution suppression

We currently do disable sources right now: we aren't sure we're keeping AI descriptions, that's how we turn off all the `flipcommons_ai_desc_*` sources. It's a kill switch that suppresses resolution of that source's claims.

### ❌ Out of scope for v1

Deferred to future versions.

#### ❌ See a source's contributions

We'll defer building a public surface exposing a source's full contribution history, like `/sources/[slug]`.

#### ❌ Cross-actor collision check

Today, username uniqueness is within `User`; nothing checks against `Source.slug`. The reserved words when creating a User are authority terms, not source slugs — opdb, ipdb, pinside aren't reserved. So a user can register username `ipdb` today and nothing stops them. In an attribution chip, "ipdb" the user reads like "ipdb" the source.

These are pre-existing issues that v1 won't address. Actor doesn't make it any worse.

The display contract is the natural mitigation. The `is_machine` on ActorModel is what disambiguates: user-"ipdb" renders as a human chip, source-"ipdb" as a source chip.

#### ❌ 3rd party bots

#### ❌ 1st party bots

#### ❌ System actor

#### ❌ Organization

#### ❌ Deleted, banned, deactivated

#### ❌ 'On behalf of' (delegation)

#### ❌ 'Assisted by' or 'Co-authored'

#### ❌ Single path through rate limiting

#### ❌ Single path through authz

v1's actors are only humans and ingest sources. Sources don't authenticate and never touch authz; a developer applies patches.

#### ❌ Single path through licensing

Licensing is 100% a source concern today, we'll revisit when humans and bots need licensing.

## Design

### `Actor`

A new table, `Actor`, to hold the resolution and attribution information about actors.

`User.actor` and `Source.actor` point to `Actor`. Attribution is carried on ChangeSet by a new field: `ChangeSet.actor`.

```mermaid
graph LR
    User -->|User.actor| Actor
    Source -->|Source.actor| Actor
    ChangeSet -->|ChangeSet.actor| Actor
```

#### What Actor is and isn't for

Actor is the resolution/attribution record: how a contributor's claims are weighed and treated. It is NOT an identity, profile, auth, or credential record. The litmus for any future field or use:

- ✅ YES: **Claim mechanics** — read by the resolver or the claim-write path without knowing the actor's type (weight, status)? → Actor.
- ❌ NO: **Identity, display, authorization, credentials, or live connection** → the backing record (User / Source / bot), not Actor.

##### Actor shall

- **be the single attribution target** — every attributed write points at exactly one Actor (ChangeSet.actor); no attribution path forks by type.
- **carry exactly one trust weight (priority) per actor**, feeding resolution for every actor type.
- **carry resolution_status describing only resolution disposition** (active / suppressed).
- **be the join key for all contribution/history queries** (filter(actor=…)); presentation stays per-type.
- **contain licensing at some point** - it's the appropriate place for licensing because that's a concern of any actor, but it doesn't make the v1 cut
- **outlive its backing record** — when a User/Source is deleted the Actor remains as the attribution anchor; deleting a backing record shall not cascade-delete the Actor (orphaned history is never lost).
- be created and linked only through `ActorModel` (see below)

##### Actor shall not

- **be the basis for authz**. What an actor may do is gated on the authenticating entity's attributes (on the User/bot satellite) through the policy engine. The single authz path is the engine, not the Actor row. (Putting authz on Actor would drag non-authenticating identities — sources — into the security domain; that's the line that kept Actor and User separate.)
- **be the basis for rate limiting** — same reason: throttling is a live-connection / credential concern, on the authenticating satellite, not the attribution row.
- **hold PII-bearing display** — a user's name, url, bio, avatar. A cached user label would outlive the deletion meant to erase it, so user identity lives only on the `User` satellite. (A **non-PII label cache** for sources/bots/orgs — MediaWiki's `actor_name` — is a sanctioned future perf option; see [Displaying attribution](#displaying-attribution).) Type-specific routing — URLs, the machine/human badge — is derived per-type regardless, never stored on Actor.
- **hold credentials** (WorkOS session, API keys). Attribution is decoupled from authentication; credentials are 1:many and live on the authenticating satellite.
- **store a semantic kind/type enum**. The only discriminator is the structural backing_model; type-specific behavior derives from the ActorModel registry.
- **let resolution_status carry an auth/access meaning**. "Can't log in" (deactivated / banned) is an orthogonal axis on the User satellite — never a resolution_status value.

#### Actor data model

`Actor`:

- `id`
- `backing_model`: name of model that backs the actor, like 'User' or 'Source'
- `priority` # replaces `User.priority` + `Source.priority`
- `resolution_status`: how claims resolution treats this actor. V1 values: `active` | `suppressed` (retain claims, but make them never win resolution -- migrated from `Source.is_enabled`)

### Where `Actor` lives

`Actor` is a new top-level app `apps.actors`, inserted into the import-linter spine just below `accounts` (above only `core`) so it is a core-only leaf everything that attributes can FK downward — the same shape as `provenance.model_bases`.

```text
provenance
 ⬇️
citations
 ⬇️
accounts
 ⬇️
actors
 ⬇️
core
```

### Remove attribution from `IngestRun`

The heart of "single path through provenance": `ChangeSet.actor` will replace today's `ChangeSet`.`user`-XOR-`ingest_run` fork. This is the single path unification: collapse to one FK where there once were two attribution channels. The `claim_author`/`changeset_author` helpers that branch on `user`-vs-`ingest_run` get rewritten to read `actor`.

`IngestRun` conflates two jobs:

- **Attribution**: its .`source` is the actor (opdb). To answer "who," an ingest `ChangeSet` goes `ChangeSet` → `ingest_run` → `source`, two hops.
- **Batch/run metadata**: `patch_id`, `input_fingerprint`, `status`, `started_at`, `note`. The "this came from patch 0042, fingerprint X, applied at T" record.

We will keep `ingest_run` as optional `batch-provenance` on ChangeSet — NULL for interactive edits, set for ingest — but it stops being an attribution channel. All that patch/fingerprint/status metadata is real and can't fold into actor; it survives, just demoted from "who" to "which batch." We replace `IngestRun.source` with `IngestRun.actor`.

Directionally, `IngestRun` will grow into a general "machine run" concept. A 3rd or 1st-party bot doing a scheduled job is also a batch of machine writes that wants a run record. We won't generalize `IngestRun` as part of v1, but separating `actor` from `ingest_run` paves the way.

### Replace `Claim.user`/`source` with `Claim.actor`

`Claim` carries its own attribution today — `user`-XOR-`source`, the same two-channel fork as `ChangeSet`. Since `ChangeSet.actor` becomes the source of truth (above), the instinct might be to drop attribution from `Claim` entirely. However, we can't, because the active-claim uniqueness constraint reads the author directly off the `Claim` row and can't follow a join to `ChangeSet.actor`:

- Today that constraint is two partial unique indexes — `(content_type, object_id, source, claim_key)` and `(…, user, …)` `WHERE is_active` (`provenance_unique_active_claim_per_source` / `_per_user`). "One active claim per author per field" must be a single-table unique index; a `Claim → ChangeSet → actor` join can't back one, so duplicate active claims would become possible under races.

So instead of dropping it, we **replace the `user`/`source` pair with a single `Claim.actor`** — a denormalized copy of `claim.changeset.actor` (`ChangeSet.actor` stays the source of truth). One column replaces two, and the two per-author indexes plus the `source`-XOR-`user` CHECK collapse into **one** index — `(content_type, object_id, actor, claim_key) WHERE is_active` — which also extends uniqueness to bots/orgs/system actors the old pair never covered. "Single path" holds: `Claim.actor` is one uniform column, not a per-type fork.

We make `Claim.changeset` required as part of this.

**Write-path invariant.** Two consistency rules must hold table-wide:

- `Claim.actor == claim.changeset.actor`
- `changeset.ingest_run IS NULL OR changeset.actor == ingest_run.actor`

Both span two tables, so — unlike the active-claim uniqueness index, which the DB enforces — neither can be a CHECK/unique constraint. They're held by (a) funneling every write through the one helper that sets both sides together, and (b) a data-integrity test asserting them across the table. This replaces `assert_claim`'s current author-consistency guards ("ChangeSet user must match the claim user" / "same IngestRun source"). The denormalization isn't free: bypass the funnel and the uniqueness index still fires — on the wrong actor, silently — which is why the test backstop matters.

### `ActorModel`

Every type of entity that is an actor -- `User`, `Source` -- would implement a new `ActorModel` [abstract base class](/docs/DataModeling.md). This is the mechanism that:

- Creates the actor record when creating the backing record
  - Maintains the `Actor.backing_model` when creating the `Actor` record.
- Sets the actor OneToOne (such as the `User.actor` field) when creating the two records
- Registers types of actors

The registration direction matters for the import-linter spine: `apps.actors` sits _below_ `accounts` (and below `provenance`, where `Source` lives), so it must **never import `User` or `Source`** — that would be a forbidden upward dependency. Instead the satellites import `ActorModel` downward (`User(…, ActorModel)`, `Source(…, ActorModel)`), and the registry is just `ActorModel.__subclasses__()` walked at app-ready — Django has loaded every model by then, so the subclasses register _themselves_ by inheriting, with no import from `actors` back up to them. Same direction as `LinkableModel` / `core.entity_types` already work.

#### No bulkification in v1

This won't work in bulk without gymanstics. That's okay; we don't create sources in data patches right now (which must be bulkified). If we need bulk later, we can cross that bridge then.

### Displaying attribution

In the UI, to display attribution, the system must find the actor(s) for the ChangeSet (once there's delegation and co-authors post v1), then figure out what type of thing each actor is (user or source or bot or whatever), then find their display name, and figure out how to link to their profile page / homepage URL / etc. To display an 'Is Machine' badge the system must also figure out what type of thing it is. A bit messy, I don't love it, but at least the mess is in the right place.

**The read path is one query, not N+1.** A list of changesets resolves all its attribution in a single query via `select_related('actor__user', 'actor__source', …)` — one LEFT JOIN per backing type (Django select_relates reverse one-to-ones; `prefetch_related` can't, but `select_related` can). In v1 that's two joins; the cost grows only with the number of actor types, not with row count. If types ever proliferate enough that the joins bite, the escape hatch is the **non-PII label cache** on `Actor` (sources/bots/orgs only — never user PII), turning the common chip render into a plain column read. Until then the join is fine.

**When the backing record is gone.** Deleting a backing record (a future, deferred capability) leaves the `Actor` standing as the attribution anchor. Attribution then renders `[deleted <kind>]` from the persisted `Actor.backing_model` (which survives the deletion) with the right machine/human badge — a first-class display state, distinct from `suppressed`/`deactivated` (where the backing record is present and fully displayable). We do **not** snapshot the deleted record's name/url onto `Actor`: for a user that is exactly the PII the deletion was meant to erase. A label snapshot is at most an optional future nicety for non-PII actors (sources, bots), never for users.

### Sequencing

Each step below is its own PR, in order.

**Testing against real data.** A Docker Postgres container (`fc-pg`) holds a very recent copy of the localhost SQLite dev DB. Any PR in this sequence should feel free to test against it — it's the best way to exercise these migrations and backfills on real-volume Users/Sources/ChangeSets/Claims and to confirm Postgres-specific DDL (partial indexes, CHECK constraints) behaves as it does on SQLite. Connect with `DATABASE_URL=postgres://pinbase:pinbase@localhost:5432/pinbase`. <!-- pragma: allowlist secret (local dev throwaway credentials) -->

#### ✅ DONE: Backfill ingest runs

Much of the initial data seed (flipcommons-catalog + the ai-desc-\* + web-scrape ones) do not have an `IngestRun` even though they were all run within seconds of each other, so each source's claims WERE created in a single conceptual ingest run. We mint a synthetic "seed" IngestRun per baseline source to carry the backfilled changesets.

This will be its own PR.

#### ✅ DONE: Backfill changesets

Create changesets for the changeset-less seed claims — ~104,078, all source-attributed (103,575 flipcommons-catalog, ~480 flipcommons-ai-desc-\*, 16 web-scrape; dev counts, prod ~similar).

- Group all changes for a given record from a given ingest source into a single ChangeSet.
- Set the ChangeSet timestamp to the timestamp of any Claim in the ChangeSet. All the bulk ingest happened at the same moment (around ~17:33:13–28 on dev, not prod). It doesn't matter which Claim is used.

Because every backfilled changeset gets an `IngestRun`, the backfill satisfies the current user-XOR-ingest_run constraint. That means "every claim has a ChangeSet" can ship as its own migration, before and independent of the Actor work — you're not forced to land Actor first. It decouples two big risky migrations.

This will be its own PR.

#### ✅ DONE: Implement Actor

- **Build**
  - Actor functionality
- **Migrate**
  - Add `ChangeSet.actor` and `Claim.actor` columns (nullable)
  - Mint an Actor for every existing User/Source
  - COPY priority from User
  - COPY priority, is_enabled→resolution_status from Source

This will be its own PR.

#### ✅ DONE: Enforce single claims write path

Make the claim-mint primitive the single, enforced chokepoint before layering actor attribution on it. Relocate the primitive off `Claim.objects` into a module-level `_assert_claim` (new `apps/provenance/claim_writer.py`) and **delete `ClaimManager`** (its only method). Validation moves up with it, retiring the `models.claim → validation` import-linter exception. Lock the chokepoint two ways: an import-linter forbidden contract (only `claim_edit` may import `claim_writer`) and an AST mint-guard test (no `Claim` _persistence_ — `objects.create`/`bulk_create`/etc. — outside `claim_writer` + ingest's `persist.py`). Route media through `execute_claims` so there's one non-ingest mint caller. Sweep tests onto a `make_claim` factory.

Ships together with "Save actor FKs" as one PR — see the commit breakdown there.

#### ✅ DONE: Save actor FKs

Write paths save `ChangeSet.actor` and `Claim.actor` going forward, so the backfill (next step) runs **once** with no fresh gaps appearing behind it.

- **Build**
  - A `record_changeset(*, actor, action=None, ingest_run=None, …)` funnel (new `changeset_writer.py`) and the relocated `_assert_claim` go **actor-first**: callers pass an `Actor`, never user/source.
  - `Claim.actor = changeset.actor`. The legacy `user`/`source` column is still populated this PR (its CHECK + unique constraints stay live until later steps) via a **model-driven stamp** — `setattr(claim, actor.backing_model, backing)`, no `if actor_type` branch and no hand-declared per-type field name (`backing_model` already names the legacy Claim FK) — deletion-scheduled for "Drop dead schema".
  - **Dedupe stays keyed on the legacy author column** this PR: historical active claims have `actor = NULL`, so an actor-keyed filter would miss them and trip the live per-user/per-source unique index on any re-edit. Actor-keyed dedupe moves to "Tighten schema" (with the unified index).
  - Ingest sets `actor` on its bulk ChangeSets/Claims (`= ingest_run.source.actor`).
  - Extend the AST guard to also lock `ChangeSet` creation to the funnel + ingest.
- **Migrate**
  - None — the `actor` columns already exist nullable.

Write-path invariants (held by the funnel plus a NULL-guarded data-integrity test, so they're safe to run pre-backfill): `Claim.actor == changeset.actor`; `changeset.actor == ingest_run.source.actor` / `changeset.user.actor`.

**One PR, four commits** (reviewed on commit boundaries): (1) relocate the mint primitive — behavior-neutral; (2) route media through `execute_claims` — behavioral, characterization-tested; (3) upload's error contract — surface 422 from `upload_media` while preserving storage cleanup; (4) save actor FKs — the actor-first funnel + stamp + invariants.

#### ✅ DONE: Backfill actor FKs

All ~222K changesets (original + backfilled) need `ChangeSet.actor` populated:

- user → user's actor
- ingest_run.source → source's actor

Then backfill `Claim.actor` from each claim's changeset: `Claim.actor ← claim.changeset.actor`.

This will be its own PR.

#### ✅ DONE: Cut over consumers

Repoint every reader of `Claim.user`/`Claim.source` (and `ChangeSet.user`/`ingest_run`) onto `actor` — before "Drop dead schema" removes the columns:

- **Build**
  - Resolution: read `Actor.priority` and `resolution_status`.
  - License resolution: repoint `resolve_effective_license` from `claim.source` to `claim.actor → Source backing record` (`SourceFieldLicense(source, field) → source.default_license`). Mechanical, still source-only — licensing the feature stays deferred; this is just surviving the loss of `claim.source`.
  - Author / display: `claim_author` / `changeset_author` and attribution display read `actor`, not `claim.source.name` / `claim.user`.
  - Revert: the "source-attributed claims cannot be reverted" guard reads `actor` (is it a machine/source?) instead of `claim.source_id`.
  - Changeset-undo authz: `is_changeset_author` (today `changeset.user_id == request.user`) reads `changeset.actor`'s backing user instead — authz still gates on the session user, just reached via `actor`.
- **Migrate**
  - No migrations in this PR.

Acceptance criteria:

- Resolved values must be byte-identical before/after; the merge must not change a single resolution winner.

This will be its own PR.

#### ✅ DONE: Tighten schema

- **Migrate**
  - Make `ChangeSet.actor` NOT NULL
  - Make `Claim.changeset` NOT NULL
  - Make `Claim.actor` NOT NULL
  - Add the unified active-claim unique index on Claim: `(content_type, object_id, actor, claim_key) WHERE is_active`

These migrations don't move data; they only change validation.

This will be its own PR.

#### Drop dead stuff

Drop dead schema:

- **Migrate**
  - DELETE priority from User
  - DELETE priority, is_enabled from Source
  - DELETE `Claim.user` / `Claim.source`, the per-source/per-user unique indexes and the `source`-XOR-`user` check (all replaced by `Claim.actor` + the unified index)
  - DELETE `ChangeSet.user` and the `user`-XOR-`ingest_run` check (replaced by `ChangeSet.actor`); re-express `action IFF user` as `action IFF ingest_run IS NULL` (interactive edits carry an action; batch/ingest ones don't). `ingest_run` itself stays — it's batch metadata now, not attribution.

Drop dead reads:

The load-bearing reads — resolution, license, author/display, history, revert and undo authz — were already repointed onto `actor` in "Cut over consumers" (that PR carries the byte-identical acceptance bar). What's left here is the dead scaffolding that only existed to service the legacy columns, removed in lockstep with deleting them:

- **The transitional legacy-author stamp** from "Save actor FKs" — the `setattr(claim, actor.backing_model, backing)` stamp helper and `record_changeset`'s `cs.user = actor.user` line. With `Claim.user`/`source` and `ChangeSet.user` gone there's nothing left to stamp, so the write funnel becomes purely actor (its end state).
- **The model field declarations + annotations** they leave behind: the `user` / `source` FKs on `Claim`, `user` on `ChangeSet`, and the `user_id` / `ingest_run_id` / `source_id` typing shims. The per-user `ChangeSet` indexes (`provenance_cs_user_created`, `provenance_cs_user_action`) go too — their actor-keyed replacement (for revert's experience gate, `ChangeSet.filter(actor=…)`) lands in "Tighten schema".
- **Cosmetic readers** that "Cut over consumers" left alone because they don't touch resolution: `ChangeSet.__str__`, provenance/catalog admin `list_display` / `search_fields`, and any `select_related("…user")` / `("source")` prefetch hints that survive — repoint to `actor` or drop.

Acceptance: a grep gate proving no non-migration code names `claim.user` / `claim.source` / `changeset.user` / `ingest_run.source` for attribution — `actor` is the only attribution read left.

This will be its own PR.

## Sketch of deferred features

This is a sketch of a future version of the `Actor` system that supports the deferred actor types and relationships.

### Delegation

A new `ChangeSet.performed_by` field. It's the Actor who actually executed the ChangeSet when its not the same Actor who authored it.

#### Delegated authz

A delegated act like {`actor`="Kineticist", `performed_by`="Pat Klein"} needs to check multiple authorizations:

- Pat may perform the action
- Pat may act for Kineticist

### Co-authors

A new table, `ChangeSetCredit`, to hold co-authors and assistants. Fields:

- `actor`: the `Actor` being credited
- `role`: the type of credit being given, such as `assisted_by`
- `changeset`: the `ChangeSet` that is the subject of the credit

AI assistance would be `{actor: Codex, role: assisted_by}`.

### Resolving attribution

Attribution would then resolve to up to three things:

| Scenario                   | `actor`    | `performed_by`                       | `credits`               |
| -------------------------- | ---------- | ------------------------------------ | ----------------------- |
| Human edit                 | the human  | —                                    | —                       |
| Ingest patch               | `opdb`     | the developer / 1st-party ingest bot | —                       |
| Pat writing for Kineticist | Kineticist | Pat Klein                            | —                       |
| AI-assisted human edit     | the human  | —                                    | `{Claude, assisted_by}` |
| System job                 | `system`   | —                                    | —                       |

## Alternatives

### Bots are Users

Make Source a User. Get rid of the Source table. No Actor table.

#### Pros

- It feels like the cheap, easy, simple approach. Every "single path" machine the doc wants already keys off User — the authz PolicyUser Protocol, rate limiting, User.priority, the /users/[username] contributions page. Collapse Source onto User and most of those goals fall out for free. The codebase even already tolerates non-loginable User rows - the createsuperuser-that-can't-sign-in.

#### Cons

- **Domain isolation**. User is the table with the densest invariants in the system: WorkOS identity, sessions, is_staff/is_superuser, email verification, the username policy/reserved-list. Drag non-authenticating rows into it and every auth-assuming code path becomes a "is this actually a loginable human?" audit — the WorkOS sync, the authz PolicyUser flow, the capabilities endpoint, any is_staff predicate. That special-casing is diffuse, permanent, and lives in the security-critical layer. The Actor approach confines the actor complexity to the attribution/display layer instead — the "mess in the right place" we already located and bounded. Bounded display machinery beats diffuse auth special-casing.
- **attribution ⊇ authentication**. Everything that authenticates is attributed; not everything attributed authenticates (sources, system, org never log in). So attribution is the superset and belongs as the base — that's Actor, with User as the authenticating specialization. This option would invert it: it makes the subset (User/auth) the base and stuffs the superset in. That inversion is the source of every awkwardness — and notice it concentrates on the non-authenticating actors. Bots-as-Users is actually defensible (bots do authenticate, via API key); sources-as-Users is the awkward part (a pure attribution identity squatting in the auth table).
- **It only relocates the 'multiple paths' problem**. This option recreates the exact problem this doc exists to fix. The opening of this doc is "we regret not rationalizing User and Source — it created multiple paths and is accruing inconsistencies." This option doesn't eliminate that; it instead relocates it into the auth domain, where every future auth feature has to re-remember non-human Users exist.

### GFK on ChangeSet

A GenericForeignKey author on `ChangeSet`. `ChangeSet.author` = `GFK(User | Source)`. No `Actor` table.

#### Pros

It's Django-native; it's what many Django devs might reach for first.

#### Cons

- A GFK can't carry shared resolution fields (priority, resolution_status)
- A GFK can't be a single stable join target for contribution queries
- A GFK can't outlive the backing record as an anchor

## Prior Art

How comparable systems model human and non-human actors.

### MediaWiki

MediaWiki (the software under Wikipedia) factors _all_ attribution into one [`actor` table](https://www.mediawiki.org/wiki/Manual:Actor_table): `actor_id` (PK), `actor_user` (nullable FK to `user`), `actor_name`. Revisions, log entries, recent changes and other attribution-bearing tables reference an actor — the [actor migration](https://www.mediawiki.org/wiki/Actor_migration) replaced duplicated user-id/user-name author fields with a single actor reference. One reference covers humans, anonymous IPs and bots alike.

A bot is **not** a distinct row type. It is a `user` account with the bot user right, commonly granted through a bot group, and bot-ness is a _flag_ recorded separately from attribution — [`recentchanges.rc_bot`](https://www.mediawiki.org/wiki/Manual:Recentchanges_table) marks the edit, while `actor_id` still carries the who. `actor_user` is nullable not only for logged-out IP edits but also "for some mass imports", so imported provenance can have an actor without a backing user. Bots get the normal user page and `Special:Contributions` listing, and system usernames are protected from human registration via `$wgReservedUsernames`.

### Wikidata

Wikidata / Wikibase run on MediaWiki, so edit attribution inherits the same account/actor machinery: humans and bots edit through user accounts, and bot edits are governed by a [bot policy](https://www.wikidata.org/wiki/Wikidata:Bots). The interesting difference is the structured-data layer. In the [Wikibase data model](https://www.mediawiki.org/wiki/Wikibase/DataModel), a `Statement` contains the claim, zero or more references, qualifiers, and a rank; references say where the value came from, while ranks (`preferred`, `normal`, `deprecated`) control which values are considered best/default and which erroneous-but-sourced values should be retained for context. That separation is useful for Flipcommons: actor attribution, source/evidence, and claim-resolution status are related but distinct concepts.

### Git

Git separates **author** (who wrote the change) from **committer** (who applied it) as two independent identity fields on every commit — the same split a patch pipeline needs, where the patch's source authored the content out of band and the ingest applied it. Crucially neither field is an account: a commit's identity is a free-form `Name <email>` string, validated by nothing, and the platform (GitHub/GitLab) _maps_ it to a real account after the fact (or leaves it as an unlinked author). That's the inverse of MediaWiki's actor table — provenance captured as data first, reconciled to an identity later — and it's the tradeoff to weigh for ingest sources.

### GitHub

GitHub exposes a GraphQL [`Actor` interface](https://docs.github.com/en/graphql/reference/interfaces) — "an object which can take actions on GitHub, typically a User or Bot" — currently implemented by `User`, `Bot`, `Organization`, `Mannequin` and `EnterpriseUserAccount`, all sharing one identity surface (`login`, `avatarUrl`, profile URL/resource path). Any action resolves to an `Actor`; the concrete type is a discriminator on top of a common contract, not a separate attribution channel.

`Bot` is "a special type of user which takes actions on behalf of GitHub Apps", so app automation still appears in the same actor channel as users. `Mannequin` is "a placeholder user for attribution of imported data on GitHub", preserving source-system authorship until it can be claimed or mapped. Bots and mannequins have the same visible identity shape as other actors, including `login`, avatar and URL fields.

### GitLab

An access token materializes an actor. Creating a [project access token](https://docs.gitlab.com/user/project/settings/project_access_tokens/) creates a **bot user** associated with that token: a real user row with a generated username like `project_{project_id}_bot_{random_string}`. The bot user receives permissions from the token's role and scopes, is a project member, is non-billable, cannot be directly added to other projects or groups, and has contributions associated with the bot user account. Revoked or expired tokens are inactive first and their bot users are retained for a period; when a bot user is removed, its contributions move to GitLab's **Ghost User**. This is the closest match to our _3rd party bots_: an API key is not just a credential but a named, attributable identity, with a standing placeholder to absorb its history once the actor is gone.

### Stack Exchange

Stack Exchange uses a single [`Community` user](https://stackoverflow.com/users/-1/community) (conventionally `user id -1`) as the visible system account for automated and community-level actions. Its profile says it is "not really a person" and is a background process that keeps the site clean; examples include poking old unanswered questions, owning community questions and answers, owning downvotes on permanently deleted spam posts, owning suggested edits from anonymous users, and removing abandoned questions. [Deleted-post documentation](https://stackoverflowteams.help/en/articles/8727985-deleted-posts) also attributes several automatic deletion paths to Community. It is one reserved, non-human user profile standing in the same attribution surface as human users.

### W3C PROV

The provenance standard models this at the ontology level. [PROV-O](https://www.w3.org/TR/prov-o/) gives `prov:Agent` three subclasses — `prov:Person`, `prov:Organization` and **`prov:SoftwareAgent`** ("running software") — and an Entity is `prov:wasAttributedTo` an Agent regardless of which subclass it is. Software is a first-class responsible party on the same footing as a person, which is precisely the claim behind treating an ingest source or a bot as a peer of a human contributor rather than a second-class "system" exception.

### Slack

Slack separates the installed app from human users, but the message stream still carries a visible actor identity. [Bot tokens](https://docs.slack.dev/authentication/tokens/#bot-tokens) represent a bot associated with an app installed in a workspace and are deliberately not tied to the installing user's identity, so the app can keep working if that user leaves. [User tokens](https://docs.slack.dev/authentication/tokens/#user-tokens), by contrast, represent workspace members and perform write actions as the user. In `chat.postMessage`, both bot and user tokens can use `chat:write`, and bot-posted messages include fields like `bot_id` and `subtype: "bot_message"`. Slack also has an explicit impersonation escape hatch: posting messages that appear to have been created by a user requires the additional [`chat:write.customize`](https://docs.slack.dev/reference/methods/chat.postMessage/#sending_messages_as_other_entities) scope and should only happen after an inciting user action. The lesson is that credentials, installation ownership and visible attribution are separate concerns: app-owned automation should usually be attributed to the app/bot, while "act as this human" needs a distinct permission and audit story.

### OpenStreetMap

OSM handles bulk imports — its analog of an out-of-band data patch — with a [dedicated import account](https://wiki.openstreetmap.org/wiki/Import/Guidelines), conventionally named `{User}_Import` and kept separate from the contributor's primary human account, with a profile that links back to the human owner and to the import's documentation. The [Automated Edits code of conduct](https://wiki.openstreetmap.org/wiki/Automated_Edits_code_of_conduct) then requires the data source to be recorded on the import account and on each changeset. Same shape as _ingest sources_: a distinct, non-human attribution identity per data origin, carrying the provenance the bulk edits can't carry per-row.
