# Claim-identity narrowing for ModelRelationship edges

Narrow the `model_relationship` edge claim's identity to `target_machine` alone. `target_label` stays a **member** — authorable, editable, materialized, displayed as the target — but with `identity=None` it leaves the `claim_key` and the reconcile row-key. This implements step 7 of [ModelRelationships.md](ModelRelationships.md) and unblocks the retheme work that follows on this branch.

Why: the label is copyedited prose. In identity, a one-word fix tombstones the edge and strands its citation history; two actors wording it differently fork two edges. Out of identity, a reword supersedes in place (same row) and disagreements contest one edge. See [Claim identity](ModelRelationships.md#claim-identity).

## Open questions

None blocking.

## Root cause: `identity` is overloaded, because the derived schema is lossy

The domain decision is sound and unchanged: `target_machine` identifies the edge; `target_label` is editable target data at a coarser resolution. The fragility is infrastructural. `ClaimRelationshipSpec` separates `members` from `payload`, but the derived `RelationshipSchema` ([validation.py:111](../../../backend/apps/provenance/validation.py)) flattens both into one `value_keys` list — the erasure happens at the registration sites: `_value_keys_for`'s `return members + payload` ([claims.py:191](../../../backend/apps/catalog/claims.py)) plus the alias and media hand-builds in the same file. Downstream code then reconstructs several independent concepts from the single `identity` field — so `identity` currently answers six different questions:

| `identity` is (mis)used to answer  | Reads it at                          |
| ---------------------------------- | ------------------------------------ |
| in the claim_key?                  | `claims.py:141`, `validation.py:538` |
| the reconcile row-key?             | `_through_projection.py`             |
| primary display, vs qualifier?     | `display.py:423`                     |
| eligible for an XOR group?         | `validation.py:220`, `checks.py:214` |
| required in a tombstone?           | `claims.py:152`, `validation.py:470` |
| authoring / materialization shape? | `emit.py:534`                        |

Every P1 that review found across the rounds was two of these silently disagreeing on the **label** edge — the claim whose identity is _routinely null_ (`target_machine:null`) yet still carries meaningful data. The fix is **not** a classifier that re-derives the erased structure (that just adds a reconstruction layer, and infers "member" from "appears in XOR" — but XOR is a validation rule, not the definition of membership). The fix is to stop erasing the structure.

## The design: a lossless `RelationshipSchema`

Preserve the spec's structure in the derived schema, and give each concept its own authoritative source. Two distinct spec types replace the single `ValueKeySpec` (adopted from typing review — this is an upgrade over the earlier one-type sketch):

```python
@dataclass(frozen=True, slots=True)
class MemberSpec:
    """Authorable, materialized member; identity optional. No `required` field —
    every member is required by construction (absence is ""/null by convention)."""
    name: ClaimValueKey
    scalar_type: type
    nullable: bool = False
    identity: IdentityPartName | None = None
    fk_target: FkTarget | None = None
    display_key: ClaimValueKey | None = None
    max_length: int | None = None

@dataclass(frozen=True, slots=True)
class PayloadSpec:
    """Qualifier data on the row — never identity, never FK, never the display subject."""
    name: ClaimValueKey
    scalar_type: type
    required: bool = False
    nullable: bool = False
    max_length: int | None = None
    min_value: int | None = None
    choices: tuple[str, ...] | None = None

@dataclass(frozen=True, slots=True)
class RelationshipSchema:
    namespace: ClaimFieldName
    members: tuple[MemberSpec, ...]
    payload: tuple[PayloadSpec, ...]
    valid_subjects: frozenset[type[ClaimControlledModel]]
    xor_groups: tuple[tuple[ClaimValueKey, ...], ...] | None = None

    @property
    def value_keys(self) -> tuple[MemberSpec | PayloadSpec, ...]:
        return self.members + self.payload
```

Why two types: it converts four registration-time runtime checks into compile-time impossibilities — `identity ⇒ required` is deleted as statically true, `display_key`/`fk_target` become member-only, `choices`/`min_value` payload-only — and deletes the dead qualifier-FK branch in display ([display.py:443](../../../backend/apps/provenance/display.py)). Registration gets simpler, not busier: `_value_keys_for` already builds the two tuples separately before concatenating, and the split mirrors the spec-side `MemberField`/`PayloadField` vocabulary so both layers share one mental model. Honest cost: consumers that iterate `value_keys` uniformly (validation rules 5/6, emit's dict-member classifier) handle the union via the shared fields (`name`, `scalar_type`, `nullable`, `max_length`), with the `choices` check moving to a payload-only pass — mild, and the rule-4 requiredness rewrite forces restructuring there anyway. Don't go farther than two: no FK-vs-literal member sub-split, and no per-namespace TypedDicts for claim values (they'd hand-maintain what Django introspection derives). The flat `value_keys` property survives as a compatibility surface for the deliberately role-agnostic consumers only — see the annotation bullet in stage 1.

| Concern                           | Authoritative source                                  |
| --------------------------------- | ----------------------------------------------------- |
| authorable / materialized members | `schema.members`                                      |
| claim + reconcile identity        | `member.identity`                                     |
| payload / qualifiers              | `schema.payload`                                      |
| positive-claim requiredness       | required members + required payload                   |
| tombstone content                 | identity only; label display derived from prior claim |
| XOR validation                    | members, positive claims only (skipped on retraction) |
| primary claim-history display     | members                                               |
| reconcile data columns            | non-identity members + payload                        |

`target_label` is then a **member everywhere**; `identity=None` excludes it _only_ from the claim key and reconcile row-key. No stored `role`, no `role_of` classifier, and no artificial "a non-identity member must be in an XOR group" invariant — membership is structural (`schema.members`), not inferred. `alias_display` becomes payload referenced by `alias_value.display_key`; `media_attachment` becomes one member + two payload; the display-target set derives once from `member.display_key` instead of being rebuilt three times.

## Staging

Four commits. The discipline — especially stage 2 — is what stops the round-by-round P1 discovery: it forces every "member ⟺ identity" assumption to fail as a test up front, not as a review finding later.

### Stage 1 — Lossless-schema refactor (behavior-preserving)

`target_label` **stays `identity=`**; full suite green; zero behavior change.

- `RelationshipSchema` carries `members` + `payload`; `value_keys` becomes the derived property above.
- Registration ([`_register_through_model_schemas`](../../../backend/apps/catalog/claims.py) / `register_relationship_schema`) passes `members` and `payload` through structurally instead of concatenating; the alias/media hand-builds declare their split explicitly.
- Repoint every `value_keys` consumer at its authoritative source per the table: `display.py` (primary = members; qualifiers = payload; display-target set from `member.display_key`, deleting the 3× `consumed_by_display` / `display_keys` rebuilds at `display.py:403`, `emit.py:430`/`:530`), `emit.py:534` (member vs payload by structure), and the validation rules (registration XOR over `schema.members`; the `:252`/`:470` overloads).
- **Projection restructuring** (bigger than a repoint): `build_through_projection` ([\_through_projection.py:114](../../../backend/apps/catalog/resolve/_through_projection.py)) keys reconcile rows by **all** `spec.members` and reads only `spec.payload` as data columns. Restructure it to key rows by identity parts only and materialize non-identity members as data columns updated in place. Behavior-preserving now (every member is identity until stage 3); this is what stage 3's reword-in-place lands on. The engine needs no change: `diff()` already emits `UpdateRow` on data inequality and `write()` bulk-updates data columns by pk.
- **Annotate the surviving flat consumers as deliberately role-agnostic** — validation rules 5/6 (type/unknown-key checks), `_collect_refs` (display), `validate_relationship_claims_batch`. The `value_keys` compat property keeps legacy code compiling, which is also how identity-based role inference quietly returns; the annotations mark the only sanctioned uses.
- **Typing ride-alongs** (cheap while the signatures are open): delete `classify_claim`'s dead `claim_key` / `value: Any` params (two call sites); rename `build_relationship_claim`'s `identity` mapping to `values` with an honest docstring — it carries payload on asserts, and the name lied ([claims.py:112](../../../backend/apps/provenance/claims.py)); use the existing `ClaimFieldName`/`ColumnName`/`ClaimFieldMap` aliases in the registry signatures; `validate_single_relationship_claim`'s `value: Any` → `object` (the `type(value) is not dict` gate already narrows). Skip per-namespace TypedDicts and the codec `Any` plumbing — documented JSON-boundary erasure, not smells. **Decision (implementation, 2026-07-15): the full member/payload param split of `build_relationship_claim` was evaluated and deliberately skipped** — the single polarity-dependent mapping is load-bearing for the patch front end (`_member_identity` builds one dict for assert and remove; the deferred-claim plumbing in `plan.py`/`persist.py` carries one `identity` dict as its plan artifact), so splitting it ripples into those shapes for a purely structural gain. Documented at the builder instead; revisit only if a caller outside the patch front end ever passes payload on a tombstone.
- **Display generalization** (this is a real consumer change, not free): `resolve_identity_label` → member-aware. Drop `assert spec.identity is not None` ([display.py:195](../../../backend/apps/provenance/display.py)); change `get_display_override` to take the `MemberSpec` itself (returning `str | None`) instead of a name it looks up in the flat list — the `next(s … if s.identity is not None)` lookup ([validation.py:348](../../../backend/apps/provenance/validation.py)) and its `StopIteration` hazard delete structurally, and the `str(override)` apologies at both call sites go with them. Rename only _internal_ symbols/docstrings to "primary part" and **preserve the wire field `ClaimDisplayValueSchema.identity`** ([schemas.py:91](../../../backend/apps/provenance/schemas.py)) — Stage 1 is behavior-preserving. A wire rename would be a separate coordinated change (backend schema + frontend `display.identity` readers + `make codegen` + API/DOM check); note `make test` does not regenerate the gitignored `schema.d.ts`, so a wire change can false-green.
- **Spec-native XOR checker** ([checks.py:214](../../../backend/apps/provenance/model_bases/checks.py) `_classify_member_xor`): relax from "identity members only" to "any `spec.members`", still rejecting payload / non-member names and overlapping groups. Add a synthetic classifier test for the contract. Behavior-preserving now (`target_label` is still a member); after stage 3 it permits the non-identity member instead of emitting `provenance.E007`. (Its flattened-schema twin at `validation.py:220` is covered by the consumer repoint above.)
- **Tombstones stay identity-only; display derives the removed value** ([claims.py:126](../../../backend/apps/provenance/claims.py)) — _reverses an earlier "carry members" note of mine, which was wrong._ A tombstone must not persist a _value_: in the patch path it is built from the authored `remove:` member ([emit.py:1166](../../../backend/apps/claim_ingest/patches/emit.py)) while presence matches by claim\*key alone (`:1185`), so after narrowing an arbitrary/stale label matches the singleton slot — storing it would record selector text as the value removed. Keep `build_relationship_claim(exists=False)` identity-only, and make label removal legible by deriving the displayed value at render time from the **chronologically prior claim** under that claim*key — `old_value`'s established contract (the immediately preceding claim in claim-log order, regardless of actor, priority or winning state; stated on `FieldChangeSchema` and pinned by `test_old_value_is_chronological_even_when_prior_claim_is_not_winner`), \_not* a reconstruction of the pre-removal resolved winner. Single-actor, chronology and resolution coincide, so a reword-then-`remove:`-by-old-wording shows the reworded value rather than the stale selector; under priority inversion the shown wording is the chronologically latest prior claim's, which may be a resolution loser — same as every other field's history. Spike result (verified): both history-assembly paths have the sequence — `build_edit_history` groups claims `claim_key → newest-first chain` and `_chronological_prior_claim_value` walks it; the changeset-detail path builds the same `by_key` map. **Unstated dependency, now stated:** the derivation finds the prior claim by the _new_ claim_key, which only works because rebuild-not-migrate guarantees no pre-narrowing label claim (under the old key format) survives on any DB. The stage-4 dev rebuild is therefore correctness-critical for label-removal display, not hygiene.
- **XOR is a positive-claim invariant, checked non-throwingly** ([validation.py:514](../../../backend/apps/provenance/validation.py)): an identity-only label tombstone (`target_machine:null`, no `target_label`) has zero groups present, so "exactly one" can't apply to retractions — skip it when `exists=false`. Independently, harden the check to `value.get(name)` (not `value[name]` at `:522`): requiredness is identity-only, so a non-identity member may legitimately be absent, and an incomplete tombstone must yield a clean `ValidationError`, never a `KeyError`. Add negative coverage for an incomplete label tombstone; canonicalize a machine tombstone's absent label to `""` in the builder so tombstone shape stays consistent. (Stage-1-only shim: stage 3 makes tombstones identity-only, at which point the label key vanishes from tombstones entirely and this canonicalization deletes.)

### Stage 2 — Generic non-identity-member contract tests

Before touching the real model, construct a **synthetic** relationship shape carrying a non-identity member and exercise every consumer, so each latent "member is identity" assumption surfaces here:

- claim construction + validation — positive requiredness (members + payload) vs tombstone requiredness (identity only);
- machine-slot **and** label-slot tombstones (the null-identity edge), **including their edit-history rendering** — a removed label edge stays legible (the tombstone×display _combination_, not each alone; this is where a stripped-descriptor regression would hide);
- patch assert / remove (emit + ingest);
- primary display + display overrides;
- reconcile create / update / delete (non-identity member materialized, and _updated in place_ on change).

This is the gate. Nothing below runs until it is green. Cost watch: the synthetic through-model + registered namespace is the one place this plan could gold-plate — if standing it up balloons, the fallback is parameterized contract assertions over the real `model_relationship` shape pre-narrowing (label still identity), keeping the gate discipline without the infrastructure.

### Stage 3 — Narrow the real identity

- **Spec** ([model_relationship.py:71](../../../backend/apps/catalog/models/model_relationship.py)): `MemberField("target_label", identity="target_label")` → `MemberField("target_label")`. Stays in `members` and `member_xor`; only leaves the key.
- **UNIQUE**: `(machine_model, target_label)` → `(machine_model)` where `target_machine IS NULL`. Edit `Meta.constraints` and mirror into the existing [0020_modelrelationship.py](../../../backend/apps/catalog/migrations/0020_modelrelationship.py) (branch-local — no new migration).
- **checks.py uniqueness — likely test-only**: the identity is now a _single nullable_ FK member (no longer half of a key pair). Traced: `_classify_uniqueness`'s E008 branch already accepts the two conditional uniques (`(machine_model, target_machine)` where set, `(machine_model)` where null) — both include the subject FK, stay within the member set and their union covers it. Write the covering test first; only touch the classifier if it actually goes red.
- **Projection codec** ([\_through_projection.py:193](../../../backend/apps/catalog/resolve/_through_projection.py)): a single nullable FK identity member must select `_int_or_none_from_column` ([\_engine.py:301](../../../backend/apps/catalog/resolve/_engine.py)), not `_int_from_column`. Correction to an earlier draft: this is a **type-honesty** fix, not a crash fix — `_int_from_column` is `cast(int, …)`, a runtime no-op, so a NULL decodes to `None` silently and downstream tolerates it. Consequence for tests: a stage-2 test written as a crash repro would false-pass; assert the declared codec/type instead. `target_machine` dodged this only by riding the compound codec paired with the label; it is now the sole key member.
- **Planner** ([edit_claims.py:596](../../../backend/apps/catalog/api/edit_claims.py)): `_RelationshipTarget` drops `label` (`:596`/`:611`) so label targets collapse to one identity slot; the label rides `_RelationshipPayload` reconcile-data (`:605`) and the current-vs-desired comparison (`:619`), so the claim build (`:621`) reads the wording from reconcile-data, not `target.label`. This is what makes a reword supersede in place instead of dropping the wording.
- **0021 migration** ([0021_lineage_fk_claims_to_edges.py:64](../../../backend/apps/catalog/migrations/0021_lineage_fk_claims_to_edges.py)): machine-edge keys change too (`…|target_label:|target_machine:<pk>` → `…|target_machine:<pk>`). Drop the `target_label:` component from `_edge_claim_key`; its lock-test (`:62`) goes red — update it. Load-bearing for **prod**: `0021` builds its collision set from stored `claim_key`s (`:90`) and the step-5 collision rule matches `(object_id, actor_id, claim_key)`; a format mismatch would hide collisions → duplicate edges. `0021` runs at deploy, first and only run (never run on prod; main tops out at catalog 0019). Test churn: `test_lineage_claim_migration.py` and [test_resolve_model_relationships.py:198](../../../backend/apps/catalog/tests/test_resolve_model_relationships.py) hardcode the old key string.
- **Editor** ([RelatedModelsEditor.svelte:204](../../../frontend/src/lib/components/pages/record/edit/editors/entity/model/RelatedModelsEditor.svelte)): dup-check by target only (drop the leading `${r.kind}|`, reword the error at `:211`); block a second describe-it row (no guard today — `kindTaken` at `:138` covers only `variant`/`remake`; disable the label toggle at `:288` when a label row exists). Note this fixes a **live pre-existing bug**, not one narrowing introduces: `relationship_type` was never identity, so "copy of X" + "conversion of X" already collide on one claim_key within a single save today — the kind-inclusive dup-check just fails to warn.
- **Docs**: `MemberField`/`MemberXor` docstrings ([claim_relationships.py:93](../../../backend/apps/provenance/model_bases/claim_relationships.py)) — a member may be non-identity. [DataPatches.md:283](../../../docs/DataPatches.md) — "Identity is the target only" and the `remove:`-by-`target_label`-wording example (`:286`) are wrong for label edges: a model holds one label slot, keyed by the slot not the wording, so a reword supersedes it and `remove:` targets the single label edge regardless of text. Same fix in [DataPatchAuthoring.md:245](../../../docs/DataPatchAuthoring.md) (`:259`) — the flippatch-facing guidance must state the singleton-label-slot rule, since a cross-patch same-actor label assert now supersedes rather than adds.
- **Tests**: two _different_ labels on one model → `IntegrityError` ([test_db_constraints.py:721](../../../backend/apps/catalog/tests/test_db_constraints.py) — the existing test inserts the _same_ wording twice, which the old UNIQUE also rejects, so only different-wording proves the singleton slot); reword-in-place → same row pk, citations intact; machine- and label-edge removal via API and patch; **a removed label edge stays legible in edit history** (API + DOM — display derives the value from the prior claim; includes reword-then-remove-by-old-wording). Frontend DOM tests ([RelatedModelsEditor.dom.test.ts](../../../frontend/src/lib/components/pages/record/edit/editors/entity/model/RelatedModelsEditor.dom.test.ts)): same machine under two kinds rejected before PATCH; second describe-it toggle disabled while a label row exists; removing/converting that row re-enables it. **Frontend raw-tombstone readers** (missed consumers, found in review): `hasMeaningfulValue` / `negated` / `simplifyClaimValue` ([change-display.ts:64](../../../frontend/src/lib/components/provenance/change-display.ts)) and `ClaimValue.svelte` read the raw claim-value shape; behavior happens to survive the narrowed label tombstone (`{target_machine: null, exists: false}` still has a non-`exists` key) but nothing covers it — add the new tombstone shape to their test matrix. **Test churn**: `get_all_namespace_keys` ([claims.py:304](../../../backend/apps/catalog/claims.py)) output for `model_relationship` shrinks to `["target_machine"]`.

### Stage 4 — Rebuild + verify prod-migration convergence

Rebuild loop — reproduces the prod deploy transform locally, infinitely repeatable:

1. `cp backend/db.pre-0039.sqlite3` over the dev DB (state: catalog migration 0012, patches ≤0038, 53 raw `converted_from` claims, no ModelRelationship table).
2. `migrate` — applies 0013–0021; `0021` transforms the 53 claims into machine-target edges with the narrowed key. The exact prod-deploy moment.
3. `ingest-patches --patches-dir ~/dev/flippatch/patches/` — layers the 0039+ patches (through 0151), machine- and label-target edges.

The rebuild exercises the label path end-to-end: 6 patches author `target_label` edges (0083, 0095, 0108, 0109, 0144, 0151) → 24 live label edges across 24 distinct models. Assert: the label-edge inventory matches **exactly** — 24 edges, diffed as (model, wording) pairs against a pre-narrowing rebuild — label claim_keys exclude the wording, and ingest + `0021` + resolve converge.

**Why exact-inventory, not "≤1 per model via the UNIQUE" (correction from adversarial review — the earlier tripwire was dead code):** after narrowing, all of a model's label edges share one claim_key, so a second label assert from the same actor **supersedes** the first at the claim layer, and the resolver materializes at most one row per (subject, claim_key). The new UNIQUE can therefore never fire on the ingest path — only on direct row writes like `0021`'s — and a per-model cardinality assert passes trivially even when an edge was silently swallowed. A swallow shows up only as a count/inventory miss. If the diff shows one, the fix is a patch rewrite (branch-local, 0039+), not a design change.

## Migration & data strategy: rebuild, not migrate

The branch is local and unshipped; prod HEAD is data patch 0038; every 0039+ patch is re-authorable. There is no legacy edge data to preserve except prod's 53 `converted_from` claims, which `0021` transforms at deploy. So: no new migration, no claim_key-rewrite migration — fold the spec/constraint change into existing branch migrations, edit `0021` in place; blow away dev and rebuild rather than preserve dev data.

## Forcing functions for retheme (do now, cheap)

Retheme (a new `relationship_type`) is a clean follow-on — type is payload, orthogonal to this session. These are tripwires, not the feature: they make the toolchain refuse a half-wired new type.

- **Type-behavior exhaustiveness guard.** `first_model_candidates()` ([machine_model.py:468](../../../backend/apps/catalog/models/machine_model.py)) and `distinct_machines_q()` (`:510`) silently default a new type to _not-subordinate / not-readmitted_. Add a per-value classification over `RelationshipType` (`subordinates?`, `readmits_from_collapse?`) with a test that fails on any unclassified value. Payoff: adding `retheme` goes red on both axes until it decides (subordinate=yes, readmit=like-a-variant, per [Re-theme](ModelRelationships.md#re-theme)).
- **Exhaustive kind picker.** `KIND_OPTIONS` ([RelatedModelsEditor.svelte:42](../../../frontend/src/lib/components/pages/record/edit/editors/entity/model/RelatedModelsEditor.svelte)) uses a plain annotation — `satisfies` only checks validity, not completeness. Back it with a `Record<RelationshipKind, …>` shape so a new wire kind forces a picker entry.

Phrase tables ([relationship-phrase.ts:28](../../../frontend/src/lib/entities/relationship-phrase.ts)) already force four `Record<EdgeKind, …>` entries per new type — nothing to add.

## Out of scope

- The `retheme` type itself, its behavior wiring, per-row edge authoring, and the 0007/0008 tag retraction — [Re-theme](ModelRelationships.md#re-theme), plan steps 8–9.
- Reshaping the subordination/re-admission querysets. Leave them extension-friendly if touched; don't generalize before retheme provides the second behavior.
- Any filtering/Pages UX for derived concepts — [Articles](Articles.md).
