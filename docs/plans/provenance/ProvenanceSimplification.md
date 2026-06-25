# Provenance Simplification

## Status: ❌ WON'T DO

**The functional case is gone.** Both this proposal and the current system resolve to the _same winning claims_. Today's de-facto behavior already _is_ "human overrides source, latest human wins": humans default to `priority = 10000`, every source sits ≤300, and recency breaks human-vs-human ties (`provenance/claim_ranking_in_db.py` orders by `-actor.priority, -created_at, -pk`). The layered model would only re-encode that same behavior structurally.

**The one compelling benefit — explaining truth to users in "last edit wins" terms — needs none of this.** Explanation is a read-time presentation concern, fully decoupled from the resolver. Everything required is already on the existing rows: human-vs-machine from `actor.is_machine`/`backing_model`, who/when from the winning claim's `actor` + `created_at`, and "overrides X" from the highest-ranked _source_ claim below a human winner. The UI can truthfully render "Edited by @dean on April 4" or "Showing pindata editorial data" today, with no change to resolution.

---

## Business Problem

This project's claims/provenance architecture was meant to solve three real problems at once:

1. preserve attribution for every catalog fact
2. allow multiple sources to disagree without destructive overwrites
3. let this project editorial data override external data cleanly

Those goals are still valid. The problem is that the current system expresses all three through one universal mechanism: priority-based claim resolution.

That has created a system that is technically coherent but hard to reason about operationally.

### Symptoms

**The mental model is unintuitive.** Most people, including AI agents, naturally think in terms of "latest edit wins" or "human override beats source data." They do not naturally think in terms of a global numeric precedence graph shared by IPDB, OPDB, this project, users, and media primaries.

**Simple product features become design-heavy.** The per-field revert plan is much more complicated than it should be because "current truth" is not a simple edit history. It is a derived result of the active-claim set plus resolution ordering. See `/Users/moses/.claude/plans/linked-mixing-piglet.md`.

**One mechanism is doing too many jobs.** Source trust, editorial override, user editing, ingest bootstrapping, relationship disputes, and media primary selection all currently lean on the same priority rule even when they are conceptually different problems.

**The system is expensive to modify safely.** Priority is not isolated to one resolver. It appears throughout resolution, ingest, validation, API winner reporting, tests, and design docs. That increases implementation cost and review risk for any provenance change.

## Research

This proposal is based on reviewing the current docs, the revert plan, and the concrete code paths where priority participates in behavior.

### 1. Priority is the core resolution rule today

The main provenance docs define the system as a two-layer model where claims are materialized through priority-based conflict resolution:

- [docs/Provenance.md](docs/Provenance.md)
- [docs/plans/provenance/ChangeSet.md](docs/plans/provenance/ChangeSet.md)

The same assumption is repeated in model and resolver docs:

- [backend/apps/catalog/models/machine_model.py](backend/apps/catalog/models/machine_model.py)
- [backend/apps/catalog/resolve/**init**.py](backend/apps/catalog/resolve/__init__.py)

### 2. Resolution code is built around effective priority

The shared resolver helper computes `effective_priority` from either `source.priority` or `user.profile.priority`:

- [backend/apps/catalog/resolve/\_helpers.py](backend/apps/catalog/resolve/_helpers.py)
- [backend/apps/accounts/models.py](backend/apps/accounts/models.py)
- [backend/apps/provenance/models/source.py](backend/apps/provenance/models/source.py)

Scalar resolution, bulk resolution, and `MachineModel` resolution all pick winners by ordering claims on:

- `-effective_priority`
- `-created_at` as the tiebreaker

Concrete code:

- [backend/apps/catalog/resolve/\_entities.py](backend/apps/catalog/resolve/_entities.py)
- [backend/apps/catalog/resolve/**init**.py](backend/apps/catalog/resolve/__init__.py)

Relationship resolution uses the same rule:

- [backend/apps/catalog/resolve/\_relationships.py](backend/apps/catalog/resolve/_relationships.py)

Validation logic also re-implements the same winner-picking logic:

- [backend/apps/catalog/management/commands/validate_catalog.py](backend/apps/catalog/management/commands/validate_catalog.py)

API serialization depends on the same ordering to decide which claim is the visible winner:

- [backend/apps/catalog/api/helpers.py](backend/apps/catalog/api/helpers.py)
- [backend/apps/catalog/api/machine_models.py](backend/apps/catalog/api/machine_models.py)

### 3. Priority is also the ingest authority model

The current ingest design relies on explicit source ranking:

- This project editorial ingest asserts claims at priority 300 and is expected to outrank external sources:
  - [backend/apps/catalog/management/commands/ingest_pindata.py](backend/apps/catalog/management/commands/ingest_pindata.py)
- OPDB is configured above IPDB:
  - [backend/apps/catalog/ingestion/opdb/adapter.py](backend/apps/catalog/ingestion/opdb/adapter.py)
  - [backend/apps/catalog/ingestion/ipdb/adapter.py](backend/apps/catalog/ingestion/ipdb/adapter.py)
- Fandom is intentionally lowest-priority:
  - [backend/apps/catalog/management/commands/ingest_fandom.py](backend/apps/catalog/management/commands/ingest_fandom.py)

This is not just implementation detail. Multiple plans explicitly describe this project as canonical because it wins by priority:

- [docs/plans/AllTheData.md](docs/plans/AllTheData.md)
- [docs/plans/catalog_data_model/field-ownership-matrix.md](docs/plans/catalog_data_model/field-ownership-matrix.md)
- [docs/plans/ingest/IngestRefactor.md](docs/plans/ingest/IngestRefactor.md)
- [docs/plans/provenance/ClaimsNextGen.md](docs/plans/provenance/ClaimsNextGen.md)

### 4. Media uses priority for a different problem

Media attachment resolution first chooses winning attachment claims per `claim_key`, then also uses priority to break conflicts around `is_primary`:

- [backend/apps/catalog/resolve/\_media.py](backend/apps/catalog/resolve/_media.py)
- [docs/Media.md](docs/Media.md)

This is a separate conceptual problem from source survivorship. "Which source is more trusted?" and "Which attachment should be the primary image?" are not the same kind of decision, but they currently share the same precedence machinery.

### 5. Tests show priority is deeply baked in

The test suite repeatedly asserts behaviors such as:

- higher priority source wins
- same priority falls back to recency
- user claims beat lower-priority sources
- disabled sources reveal lower-priority winners
- higher-priority `exists=False` disputes suppress lower-priority relationships
- higher-priority media primary claims beat lower-priority ones

Representative tests:

- [backend/apps/catalog/tests/test_resolve.py](backend/apps/catalog/tests/test_resolve.py)
- [backend/apps/catalog/tests/test_api_claims.py](backend/apps/catalog/tests/test_api_claims.py)
- [backend/apps/catalog/tests/test_source_enabled.py](backend/apps/catalog/tests/test_source_enabled.py)
- [backend/apps/catalog/tests/test_resolve_bulk.py](backend/apps/catalog/tests/test_resolve_bulk.py)
- [backend/apps/catalog/tests/test_resolve_credits.py](backend/apps/catalog/tests/test_resolve_credits.py)
- [backend/apps/media/tests/test_media_claims.py](backend/apps/media/tests/test_media_claims.py)

There are over a hundred priority references in tests alone. This is a strong signal that priority is not a narrow implementation choice; it is a system-wide contract.

### 6. The revert complexity is not caused only by numeric priority

The linked revert plan is complicated partly because of priority, but mostly because the data model is:

- append-only claim history
- multiple simultaneously active claims from different actors
- resolved truth derived from the active claim set rather than stored as a snapshot

That means "revert claim X" is inherently "remove X from the active set and determine what now wins."

That remains true even under pure last-edit-wins. So changing the winner rule alone does not make revert simple enough. It helps, but it does not remove the core complexity introduced by derived truth and concurrent active claims.

## Findings

### Finding 1: pure priority resolution is not a common collaborative-edit mental model

Priority-based survivorship is common in master data management, configuration layering, and policy precedence systems. It is much less common as the main editing model for a collaborative catalog or wiki-style product.

For a product with user editing, edit history, and future revert/review workflows, people expect one of these models:

- latest accepted edit wins
- human override beats machine-imported data
- explicit canonical selection

They do not expect "winner is whichever active claim has the highest numeric precedence, with recency only as a tiebreaker."

### Finding 2: pure last-edit-wins would simplify the mental model but break important behavior

If this project switched to pure global last-edit-wins for all claims:

- a later OPDB ingest would beat an earlier this project claim unless this project was re-asserted later
- source ordering would quietly become pipeline-order semantics
- user edits and machine ingest would compete in one flat timestamp stream
- editorial disputes such as higher-trust `exists=False` claims would need a new mechanism
- media primary behavior would still need separate rules

So pure last-edit-wins is not a good direct replacement for the current system.

### Finding 3: the real problem is that one universal resolver is carrying multiple concepts

The current system is using one mechanism to represent:

- source trust
- editorial canonicality
- user overrides
- source disagreement
- relationship disputes
- UI-facing primary selection

Those should not all be the same thing.

### Finding 4: the best simplification is to separate source survivorship from human editing

The clearest simplification path is not "replace priority with LWW everywhere."

It is:

- keep source-level survivorship for external and editorial data
- introduce a distinct human override layer with a simpler editing model
- stop using numeric user priority as part of the same universal winner rule

That preserves the real advantages of the current ingest model while giving users and future editing features a much more understandable mental model.

## Proposed Direction

Adopt a **hybrid two-layer resolution model**:

1. **Source layer**
   - Sources continue to assert claims.
   - Source-vs-source conflicts continue to use explicit source precedence.
   - This project editorial data remains canonical over OPDB/IPDB/Fandom where intended.
   - `Source.priority` remains, but its meaning narrows to source survivorship.

2. **Human override layer**
   - User edits are treated as overrides on top of the source-resolved baseline.
   - Within the human layer, use **last human edit wins** per field or relationship claim key.
   - Remove `UserProfile.priority` from resolution semantics.
   - Human editing no longer competes with source claims in one flat numeric ranking.

3. **Final resolution**
   - If a human override exists for a field or claim key, it wins.
   - Otherwise, use the resolved winner from the source layer.

This gives this project a much simpler story:

- external sources compete with each other by trust
- humans override the source baseline
- the latest human override is the active human truth

That is much easier to explain, reason about, and build features on top of.

## Why This Direction

### It preserves the ingest model that this project actually needs

This project editorial data currently bootstraps the catalog and is intended to stay canonical. The source layer preserves that.

OPDB over IPDB, this project over both, and Fandom below both still work naturally.

### It matches the editing model users actually expect

For human editing, "latest human override wins" is intuitive.

It also produces much saner reasoning for:

- edit history
- revert
- moderation/review
- explaining why the page shows what it shows

### It narrows the meaning of priority

Today priority means both "source trust" and "editor/user authority." That is too much.

After simplification:

- `Source.priority` means source precedence only
- user precedence is temporal, not numeric

This is a smaller, cleaner concept.

### It removes an especially awkward part of the current model

`UserProfile.priority` is difficult to justify as a long-term product primitive. It creates a hidden authority hierarchy between humans and sources, and between humans themselves, without giving the UI or editing flows a clean way to explain it.

The proposed model removes that burden.

## Non-Goals

This proposal does **not** recommend:

- converting the whole system to pure global last-edit-wins
- removing claims/audit history
- replacing claims with direct mutable fields
- changing this project's rule that catalog truth remains claim-backed
- solving revert entirely by changing the winner rule

The claims/audit model remains valuable. The simplification is about narrowing what resolution is responsible for.

## Implications

### Revert becomes simpler, but not trivial

Under the hybrid model, reverting a human edit becomes:

1. deactivate the target human override
2. if an older human override exists for that field or claim key, that becomes active
3. otherwise fall back to the source-layer winner

That is materially simpler than today's "remove one claim from a mixed priority graph and determine what survives underneath," but it still operates in a claims/history model rather than a snapshot model.

### API/UI explanation becomes much clearer

Instead of exposing "winner because source priority 300 beat source priority 200," the UI can explain:

- "Showing this project editorial data"
- "Overridden by user edit on April 4, 2026"

That is a better product story.

### Media should likely be partially decoupled

Media attachment survivorship can still be claim-based, but primary-image selection should be reconsidered separately.

The current primary rule mixes:

- attachment existence
- explicit `is_primary`
- source precedence
- fallback auto-promotion

That is a distinct editorial/UI problem and should not drive the overall provenance model.

### This is still a significant refactor

Even though the conceptual simplification is strong, the code and docs footprint is large. The change would touch:

- resolver helpers
- scalar and relationship resolution
- API winner reporting
- validation utilities
- edit history / revert logic
- user profile semantics
- many tests
- multiple design docs

This proposal is therefore a direction document, not a request for an immediate drop-in implementation.

## Migration Direction

If this project decides to pursue this, the migration should be staged.

### Phase 1: lock the conceptual model

Decide and document:

- source precedence remains for source-vs-source survivorship
- human overrides are a distinct layer
- user numeric priority is removed from the winner rule

### Phase 2: introduce layered winner calculation

Refactor resolver internals so winner selection is explicitly two-step:

1. pick source winner
2. overlay latest human winner if one exists

Do this before changing higher-level features.

### Phase 3: remove user priority from behavior

Deprecate `UserProfile.priority` as a resolution input.

It may remain temporarily in the schema for migration compatibility, but it should stop affecting truth.

### Phase 4: update feature logic that currently assumes global priority

Review:

- edit history winner labeling
- revert logic
- moderation/review plans
- source-enabled fallback behavior
- any relationship dispute semantics that currently rely on high-priority `exists=False`

### Phase 5: revisit media primary policy separately

Do not let media-primary edge cases dictate the main provenance model.

## Recommendation

This project should **not** switch to pure global last-edit-wins.

This project should also **not** keep the current universal priority resolver unchanged.

The recommended direction is:

- keep claims
- keep source precedence for source survivorship
- remove user priority from resolution
- make human edits a separate last-human-edit-wins override layer

That preserves the good parts of the current system while removing the part that is hardest for humans and AI agents to reason about.

In short:

**Keep claims. Keep source survivorship. Simplify human editing.**
