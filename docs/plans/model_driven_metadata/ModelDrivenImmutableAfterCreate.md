# Immutable After Create

## Status: not started

No `immutable_after_create` ClassVar or enforcement guard exists yet — this is the one piece of [ModelDrivenClaimsMetadata.md](ModelDrivenClaimsMetadata.md) still planned. The forward-path code it patches has since moved in the `edit_claims.py → claim_write.py` split ([ModelDrivenClaimWrite.md](ModelDrivenClaimWrite.md) Step 0); the call sites below are updated to the new home.

## Context

This work is a pre-condition for [ModelDrivenLinkability.md](ModelDrivenLinkability.md), and an instance of the broader pattern described in [ModelDrivenMetadata.md](ModelDrivenMetadata.md): encode per-model behavior on the model itself and consume it generically from shared infrastructure.

`ModelDrivenLinkability.md` proposes a `LinkableModel` that supports models with multi-segment URL identity — specifically Location, whose `public_id` is the materialized `location_path` (encoding ancestry). Once a row's URL is materialized from `parent` + `slug`, re-parenting becomes prohibitively expensive: it would invalidate the entity's URL and every descendant's URL, and force every reference to chase the change. We opt out of re-parenting Location entirely.

This doc specifies the generic mechanism that lets Location declare that opt-out without leaking `isinstance(model, Location)` into the claims executor. It's a [base class / mixin](ModelDrivenMetadata.md#pattern-base-class--mixin) ClassVar on `ClaimControlledModel`, defaulted empty, consumed by the claims executor before each write.

## The contract

`ClaimControlledModel` declares:

```python
immutable_after_create: ClassVar[frozenset[str]] = frozenset()
```

Default empty — every existing model is unaffected. Location declares:

```python
immutable_after_create: ClassVar[frozenset[str]] = frozenset({"parent", "slug"})
```

`slug` is included because Location's `location_path` (the URL-identity field exposed via `LinkableModel.public_id`) is materialized at create time from `parent + slug`. Mutating `slug` post-create would stale the row's `location_path` (and every descendant's path) the same way re-parenting would — same cascade-cost, same corruption mode. CLAUDE.md's "slugs are editorially curated and must be claim-controlled" rule still holds in the abstract: Location's `slug` field stays claim-controlled (writable through claims at create time, with provenance), but is frozen post-create as a consequence of path materialization. This is the only model where slug is locked; for every other LinkableModel, slug remains freely editable.

`name` is **not** frozen. Names are corrected for typos, encoding errors, and official renames; no derived field on Location depends on `name`. The frontend's name→slug auto-sync is suppressed for entities whose slug is immutable (see [Frontend implications](#frontend-implications)).

The claims executor, before committing a claim write that targets an `immutable_after_create` field, checks: would the **projected resolution winner** differ from the row's current value? If so, raise `ValidationError` and abort the transaction.

## Projected winner, not spec value

It would be tempting to say "compare the asserted claim's value to the row's current value." That is wrong on every path:

- **Forward path**. Resolution picks by source/user priority and then recency. A user-asserted `parent=B` claim against a higher-priority source claim of `parent=A` doesn't change the winner — the row stays at A. Comparing `spec.value=B` to `current=A` would reject this benign no-op write even though the row would not change.
- **Bulk/ingest path**. Same priority resolution applies. A new source claim may or may not become the winner.
- **Revert path**. Reverts don't write a new value; they toggle existing claims. The toggled claim's `value` is _not_ the post-revert winner — that winner is whatever claim resolution promotes after the toggle, which may be an older claim with a different parent.

The uniform rule across all paths is therefore:

```python
projected = compute_projected_winner(entity, field)  # post-write resolution
current   = current_row_value(entity, field)          # via claim_fk_lookups for FKs
if projected != current:
    raise ValidationError({field: [...]})
```

A single algorithm, no path-specific shortcuts. Each entry point applies its mutation (assert claim, write bulk batch, toggle on revert) inside the open transaction, computes projected winners by re-running the resolver against the now-pending claim graph, and rolls back if any immutable field's projected winner differs from the current row value.

### Implementing `compute_projected_winner`

The existing [\_compute_winning_claim_ids](../../../backend/apps/provenance/history.py) in `apps/provenance/history.py` already encodes the resolution rule (active + source enabled, ordered by `effective_priority`, `created_at`, `pk`, deduped by `claim_key`). It returns claim PKs and is private to that module. Generalize it into a public helper rather than duplicating the ordering logic:

```python
# apps/provenance/history.py (or a new apps/provenance/resolution.py)
def compute_winning_claims(ct: ContentType, entity_pk: int) -> dict[str, Claim]:
    """Return {claim_key: winning Claim} for an entity. Same rule as
    _compute_winning_claim_ids; returns the claim itself so callers can
    read .value without a second query."""
```

Then `_compute_winning_claim_ids` becomes a thin wrapper (`{c.pk for c in compute_winning_claims(...).values()}`) and the immutability check reads `compute_winning_claims(ct, entity.pk)[claim_key].value` for the projected value. Because the helper runs inside the same open transaction as the just-written claims, the "pending" graph is just the live DB state — no separate simulation layer is needed.

This formulation also drops the `pk is None` discriminator from earlier drafts — it's no longer needed. Create flows pre-populate `row_kwargs` with the immutable column values that match the initial claims (the row is created with `parent=A`, then the claim asserts `parent=A`); projected winner equals current row value, no mutation, the check is a no-op. See [Interaction with the create flow](#interaction-with-the-create-flow) for why this works without a CREATE bypass.

A top-level country with `parent=None` is frozen at `None` once persisted: a later attempt to set `parent=Y` resolves to projected=Y, current=None, which differs, so the write is rejected. That's the "country can't become a state" semantic, and it falls out of the projected-vs-current rule without a special case.

## Comparing FK fields

For a foreign-key field, `getattr(entity, field_name)` returns the related model instance, while `spec.value` is the lookup-key string the claim system stores (slug by default, overridden via `claim_fk_lookups`). To compare apples to apples, the executor derives `current` the same way the claim writer does:

```python
lookup_key = type(entity).claim_fk_lookups.get(field_name, "slug")
related = getattr(entity, field_name)  # may be None
current = getattr(related, lookup_key) if related is not None else None
```

`current` and `spec.value` are then both strings (or both `None`), making `current is not None and current != spec.value` well-defined. Scalar fields use `getattr(entity, field_name)` directly with no lookup-key indirection.

## Scope: scalars and singular FKs only

`immutable_after_create` is meaningful only for scalar fields and singular FKs — the kinds where "the current row value" is well-defined. Relationship/M2M claims (credits, aliases, abbreviations, etc.) don't fit the framing and are out of scope; declaring one in `immutable_after_create` is a programming error.

Validate this at **startup**, not at write time. Add a Django system check (`@register` in `apps/provenance/checks.py`) that walks every `ClaimControlledModel` subclass and asserts each name in `immutable_after_create` resolves to a scalar or singular FK field. A bad declaration fails `manage.py check` (and therefore CI and `runserver`) before any data is touched, instead of waiting for the first write against that model in production.

## All claim-write paths are in scope

The invariant is about the row, not the actor. Every entry point that can change a claim's winning value for an `immutable_after_create` field must run the check. Concretely:

- **User edits** via `_write_claims_in_changeset` (called by `execute_claims` / `execute_multi_entity_claims`).
- **Reverts** via `apps/provenance/revert.py` (`execute_revert`, `execute_undo_changeset`).
- **Ingest / bulk** via `bulk_assert_claims`. If a source flips a Location's `parent` between ingests, the resolver would silently re-parent the row and corrupt `location_path` for the entire subtree. Ingest is not exempt.

Any future claim-write entry point inherits the same obligation. The natural factoring is a single helper that lives in a new module `apps/provenance/immutability.py`:

```python
def check_immutable_after_create(entity: ClaimControlledModel) -> None:
    """Raise ValidationError({field: [...]}) if any field in
    type(entity).immutable_after_create has a projected winner that
    differs from the row's current value. No-op if the set is empty."""
```

The helper does its own resolution via `compute_winning_claims` — callers do not need to pass projected winners in. Call sites:

- **Forward path**: [\_write_claims_in_changeset](../../../backend/apps/claim_edit/claim_write.py) (`backend/apps/claim_edit/claim_write.py`, split out of `edit_claims.py` in Step 0 and relocated to the `claim_edit` app in Step 4) — call once after the per-spec `assert_claim` loop completes, before returning. The surrounding `transaction.atomic` in `execute_claims` rolls back on raise.
- **Bulk path**: [bulk_assert_claims](../../../backend/apps/provenance/models/claim.py) (`backend/apps/provenance/models/claim.py:167`) — call after the batch insert, before the enclosing transaction commits. Per-row error surface is whatever the bulk caller already uses for `ValidationError`.
- **Revert path**: [execute_revert](../../../backend/apps/provenance/revert.py) (`backend/apps/provenance/revert.py:41`) — call after toggling claims active/inactive, before commit. Same applies to `execute_undo_changeset`.

## Error surface

The new check raises `ValidationError` with a field-scoped `message_dict` (e.g. `{"parent": ["This field cannot be changed once set."]}`). However, the current `execute_claims` catch path flattens this:

```python
except ValidationError as exc:
    raise_form_error("; ".join(exc.messages))
```

`exc.messages` discards the field key, so a field-scoped error becomes a generic `form_errors` entry. The fix is small and benefits any future field-scoped `ValidationError` from claims, not just immutability — it is a precondition for this work, not optional polish.

`StructuredValidationError` (`apps/core/exceptions.py`) already carries a `field_errors` dict, so the new surface is a sibling to `raise_form_error`:

```python
def raise_field_errors(field_errors: dict[str, list[str]]) -> NoReturn:
    """Raise a structured 422 with per-field messages."""
    raise StructuredValidationError(
        message="; ".join(f"{f}: {'; '.join(msgs)}" for f, msgs in field_errors.items()),
        field_errors=field_errors,
    )
```

Both catch sites in `execute_claims` (now in `apps/claim_edit/claim_write.py`) change to:

```python
except ValidationError as exc:
    if hasattr(exc, "message_dict"):
        raise_field_errors(exc.message_dict)
    raise_form_error("; ".join(exc.messages))
```

The bulk and revert entry points have their own error surfaces; each must surface the field-scoped message in whatever form its caller expects (per-row error in bulk, structured response on the revert endpoint). The helper raises a uniform `ValidationError` with `message_dict`; the catch sites adapt.

## Interaction with the create flow

`create_entity_with_claims` ([backend/apps/catalog/api/entity_create.py](../../../backend/apps/catalog/api/entity_create.py)) creates the row via `model_cls._default_manager.create(**row_kwargs)` **before** calling `execute_claims`. So when initial claims fire, `entity.pk is not None` — there is no "unsaved row" window to exploit, and earlier drafts of this plan that gated on `pk is None` were wrong.

The projected-vs-current rule handles this without a CREATE bypass:

1. Caller passes `row_kwargs={"parent": A_location, "slug": "foo", ...}` plus `claim_specs=[ClaimSpec("parent", "...A's location_path..."), ClaimSpec("slug", "foo"), ...]`.
2. Row is created with `parent=A`, `slug="foo"`. `current_row_value` for both immutable fields equals what the initial claim asserts.
3. `execute_claims` asserts each claim, runs resolution, computes projected winners. Projected `parent` = A (only claim, becomes winner), projected `slug` = `"foo"`. Both equal current. Check is a no-op, write succeeds.

This places a contract on every create caller for an entity with `immutable_after_create` fields: `row_kwargs` and the matching initial `ClaimSpec`s **must agree on every immutable field**. A mismatch is a programming error and the check will reject the create — which is the right behavior, since the row would otherwise diverge from its provenance record. The contract is mechanically simple to satisfy: callers already pass both, so this is a code-review item, not a runtime concern.

The check therefore runs uniformly across all paths — forward, bulk, and revert — at the same point: after applying the path's mutation (assert, batch, or toggle) and computing projected winners, before transaction commit.

## Tests

At minimum:

### Backend — parent (FK)

- **Create allowed (matching row_kwargs and claim)**: `create_entity_with_claims` with `row_kwargs={"parent": A, ...}` and a matching `ClaimSpec("parent", A.location_path)` succeeds — projected winner equals current row value.
- **Create rejected on row/claim mismatch**: `row_kwargs={"parent": A, ...}` with `ClaimSpec("parent", B.location_path)` raises (projected winner B ≠ current A). Surfaces the contract that creates must self-consistent.
- **No-op edit allowed**: re-asserting `parent=A` when row's current `parent` is `A` passes (projected = current).
- **Lower-priority claim allowed**: row's `parent` is currently A (won by a high-priority source claim). User asserts `parent=B`. The user claim doesn't outprioritize the source, so projected winner is still A. The check passes — this is the case `projected = spec.value` would have wrongly rejected.
- **Mutation rejected**: writing `parent=B` (where the user claim **does** become the winner) raises `ValidationError` with `message_dict={"parent": [...]}`. Verify the catch path produces a field-scoped 422, not a flat form error.
- **Top-level frozen at None**: on an existing top-level Location with `parent=None`, a write that would project `parent=<country>` is rejected.
- **Revert via promoted older claim is blocked**: row's winning `parent` claim is X (A); next-priority claim is Y (B). Revert claim X. Expect `ValidationError` because projected post-revert winner is Y/B, current is A.
- **Revert that doesn't change the projected winner is allowed**: e.g. reverting a non-winning claim, or reverting a claim whose next-in-line agrees on `parent`.
- **Bulk/ingest mutation rejected**: a `bulk_assert_claims` call that would change projected `parent` from A to B raises and rolls back; per-row error surface is the bulk path's standard one.
- **FK lookup-key is honored**: the comparison uses `claim_fk_lookups["parent"] = "location_path"`, so a re-parent attempt across two countries that share a slug is still detected via path comparison.

### Backend — slug (scalar)

A scalar immutable field can fail independently from the FK lookup path; cover slug separately.

- **Slug create allowed**: `create_entity_with_claims` with `row_kwargs={"slug": "il", ...}` and `ClaimSpec("slug", "il")` succeeds.
- **Slug no-op edit allowed**: re-asserting `slug="il"` when row's `slug` is already `"il"` passes.
- **Slug mutation rejected**: writing `slug="illinois"` on an existing Location with `slug="il"` raises `ValidationError` with `message_dict={"slug": [...]}`. Verify the field-scoped error reaches the API surface.
- **Slug bulk mutation rejected**: ingest path that would project a slug change is rejected.
- **Empty default is inert**: a model with no `immutable_after_create` declaration accepts arbitrary slug and parent edits (regression guard against base-class leakage).

## Frontend implications

LocationCrud does not expose a name editor for Location. Names, slugs, and parents are pindata-authoritative: corrections flow `pindata markdown → re-ingest → bulk_assert_claims`, not through the user-facing app. The Location edit page renders name, slug, and `location_path` as read-only display, and only mutable fields (description, divisions, location_type, code, short_name) get editors.

This avoids the entire `NameEditor` / slug-sync hazard: `NameEditor` is never instantiated for Location, so its `reconcileSlug` auto-sync never fires for an immutable slug, and no slug claim is ever emitted from a benign name edit. The server's immutability check is still the enforcement boundary, but the frontend doesn't need to know about `immutable_after_create` at all today.

**Deferred work — only needed if a future model wants both a `NameEditor` and an immutable slug:**

- Extend `export_entity_meta` to emit `immutable_after_create` per entity into `ENTITY_META`.
- Teach `NameEditor` to read `ENTITY_META[entity_type].immutable_after_create` and (a) skip `reconcileSlug` when `"slug"` is in the set, (b) render the slug `TextField` as read-only.
- Parity test in `entity-meta.test.ts` so backend declarations don't drift from the emitted file.

None of this is required for Location. Drop the frontend tests below from the immediate scope; they belong to the deferred work above.

## Why this lives on `ClaimControlledModel`

Like `claim_fk_lookups`, this is a claim-write concern, not a linkability concern. It's documented separately from the broader linkability work because Location's path materialization is what forces the opt-out, and the linkability contract is what makes re-parenting expensive in the first place. The mechanism itself is generic — any future model that needs immutable-after-create fields gets it for free, with no `isinstance` checks anywhere in the claims code.
