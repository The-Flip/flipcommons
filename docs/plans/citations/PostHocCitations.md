# Post-Hoc Citations

Allow users to attach citations to support facts after the fact.

## The problem

We've been building a lot of data patches that use our [analytics foundation](../../../scripts/analysis/README.md) to mine the IPDB free text notes for information. In those patches we quote and cite IPDB, but often the IPDB note mentions that IPDB's original source of the information was from a non-digital source such as Billboard (a magazine), the Encyclopedia of Pinball (a book), and other citation sources.

Some examples:

- Flippatch's `/patches/0187-victory-games-kits.yaml` cites IPDB, who themselves attribute all the information to particular volumes of Billboard (a magazine), in a fairly regular textual formulation that would be amenable to extraction via parsing.
- Flippatch's `/campaigns/0079-italian-makers/README.md` has a `corroborations.csv` "ledger" of exactly these types of deferred cites.

Those print citation sources are the original source of the information. We want to create citations for those.

Unfortunately, the system does not currently allow users to add citations to a claim after the fact.

## The core idea

Rather than fix this in some narrow way, like solving just the data patch problem, we'll build the general solution: enable actors to manage / garden the `CitationInstance`s on their existing `Claim`s after the fact.

Example:

> Alice claimed Godzilla's year is 2012. Months later she finds both a Billboard issue and a Flipz book that backs it. She wants to attach that evidence, without re-asserting 2012 (which our UI wouldn't let her do anyway).

This would create a new `ChangeSet`:

```text
  ChangeSet #1 - Alice's original edit
    ├─ Claim ⓐ: Godzilla.year = 2012
    └─ Edge X: Claim ⓐ ◀──▶ CitationInstance: IPDB

  ChangeSet #2 - Alice's later citations
    ├─ Edge Y: Claim ⓐ ◀──▶ CitationInstance: Billboard
    └─ Edge Z: Claim ⓐ ◀──▶ CitationInstance: Flipz
```

⬆️ An 'edge' is a `ClaimCitationInstance` row; it links one `Claim` to one `CitationInstance`.

The post-hoc citations attach their evidence to a `Claim` that **already exists**, without asserting a new fact / `Claim`. The `ChangeSet` containing the actual Claim does not change. The original `Claim` is never rewritten — same value, same `created_at`, same resolution rank — so `Claim` immutability holds; only the evidence around it accretes and retracts.

We'd give the `ClaimCitationInstance` edge the same lifecycle `Claim` already carries — its `ChangeSet`, an `is_active` flag and a `retracted_by_changeset`:

```text
  Edge Z:
     claim                      → Claim ⓐ          (the claim this evidence backs up)
     citation_instance          → Flipz            (the source)
     🆕 changeset               → ChangeSet #2     (the changeset that created this edge)
     🆕 is_active               → true             (whether edge is active or deactivated)
     🆕 retracted_by_changeset  → null             (FK to a ChangeSet that retracts it)
```

The new `ChangeSet` would not contain any Claims; instead, it would only add edges linking CitationInstances to pre-existing Claims owned by earlier ChangeSets, or retract edges. This is a coherent evolution of the existing system; a `ChangeSet` whose payload is a lifecycle change rather than a new claim already exists: a **revert** is exactly that — a claim-less `ChangeSet` that deactivates a `Claim` it did not write. Post-hoc citations apply that same pattern to edges instead of claims.

The citation gardening verbs:

- **Add** mints edge rows on an existing `Claim` under a new `ChangeSet`.
- **Remove** retracts an edge by flipping `is_active`, never deleting.

## Who can manage citation instances on claims

Any signed-in contributor may garden the citation instances on their own claims.

### No cross-actor citations

We will not allow an actor to attach or otherwise alter citation instances on the claims of another actor. Reason being, if the original actor retracted their claim, the value would go away, along with the other actor's citations.

Instead, each actor should assert the fact themselves, with their own citations. The UI doesn't support this now; we should add an ["I agree" UI](#an-i-agree-ui).

## No gardening of inline cites

Description fields use inline `[[cite:]]` footnotes. Actors can already add and remove these by editing the description. And those citation instances are NOT included in the `ClaimCitationInstance` join table, so it would add complexity to add support for inline cites to this system. Since it would add complexity and is unnecessary, we're not doing it.

## Rate limiting

Should be same as the current rate limits on a contributor creating changesets and citation instances.

## UX

I see the following UX surfaces where people _might_ want to go to add and view citations:

### Global changelog

At `/changesets`.

#### Viewing

The global changelog displays ChangeSets and their Claims. This UI handles revert ChangeSets specially: it finds the original ChangeSet and displays the original claim as reverted. I imagine we'd do something similar with Citation-only ChangeSets, show them within the original claim. Somehow visually distinguish the evidence added later, and visually distinguish deleted (retracted) citations.

#### Editing

Let's not introduce citation gardening inline on this page, it'd add complex UI for an infrequent use case. Insetad link to the [claim detail page](#claim-detail-page).

### Entity edit history

Like `/models/medieval-madness/edit-history`.

Whatever viewing and editing UX the [global changelog](#global-changelog) uses will also be used here. Same consistent UI for both surfaces. This is simplified by the fact that both pages use the same Svelte component to render the claimset and its claims and its citations.

### Entity sources

Like `/models/medieval-madness/sources`.

This page doesn't currently show citations at all, so for v1 we're not going to touch it. However, it's a pretty important gap. Nowhere does the system show what citations support each existing value, regardless of what claim or changeset they come from. The sources page is the logical place to do that. This should be done as a close [follow-up](#citations-on-entity-source-page).

### Entity record detail

Like `/models/medieval-madness`.

**Editing**. Here, the user isn't thinking in terms of updating THEIR claim, even if their claim happens to be the current winner. Instead, the user is just wanting to add a citation to the current value. This is the same case as [cross-actor agreement](#an-i-agree-ui). For v1 we won't touch it.

### Claim detail page

The system doesn't currently have a detail page for showing an individual claim. Let's add one, and enable citation instance gardening there.

- **Route**: `/claims/[id]`
- **Labels**: even though this is the claim detail page, we haven't exposed the word 'claim' to users thus far. We won't use the word 'claim' in the UI, such as labels, text and error messages shown to users. Instead we'll call this a 'change'. A 'ChangeSet' has multiple 'Change' items in it. I'm not super happy with this, feel free to argue. TBD.
- **Superseded claims**. Viewable, but read-only: no citation instance gardening.
- **Inline [[cite:]] footnotes**. Inline cites on a description claim carry no edges. Show them read-only on the page (they are evidence for that claim's text), but they're edited in the markdown, not here. Needs to be visually distinct from edges or it'll confuse.

### An "I agree" UI

The UI doesn't currently enable a user to say, "I agree with the site's current value here, here's some additional citations that support it". We should have a way for a user to do this. It would create a new claim and attach the citations to that claim.

A consequence: it would make the new claim the winning one, which is fine, but that new claim wouldn't contain the citations of the previous claim, and if you're looking at entity edit history, you might be confused about where they go. The answer is that that's not the right place to go to see all the citations supporting the current value. The right place is the [entity's Sources page](#entity-sources), which doesn't currently show citations at all. It should; it should show ALL citations for ALL claims that agree with the current winning value. But not for v1 of this feature.

## Data patches

The data patch grammar needs a new entry kind. Something that says "attach evidence to an existing claim, assert nothing."

The patch system currently rejects patches with no values. We must exempt the new entry kind.

How do we identify an existing claim? Usually data patches are by slug. TBD.

## Alternatives

### ❌ Mint new claim

For the same-actor case, we could create a new claim re-asserting the same fact. Currently there's no way to do this from the UI, but the back end sorta kinda supports it. However, if we simply dusted off the existing back end, it would lose the old citation instances. Instead, a real version would mint a superseding claim carrying old + new citation instances.

Cons:

- Value-identical claims churning the stream.
- `created_at` resets (resolution's tiebreaker after priority).
- Edit history shows a "change" with no value delta.
- You must explicitly carry forward prior cites, which is semantically weird.
- It doesn't generalize: the claim's identity keeps moving every time evidence accretes.

Pros:

- Zero schema change, claims stay immutable, attribution rides the new changeset.

### Alter Claim Without New ChangeSet

Allow an actor to manage the citation instances on their `Claim` directly, without attaching the changes to a new `ChangeSet`.

One version of this is a complete nonstarter, bare edge mutation:

- **It fabricates the audit trail**. Every read path infers an edge's who/when from `claim.changeset`, because today edges are born with their `Claim`. So an edge someone adds today renders as evidence that was part of the original 2012 assertion. Not "unattributed" — actively wrong.
- **Remove is a hard delete**. This violates retract-don't-delete and loses the history of the removal. To avoid that you bolt `is_active` back onto the edge — plus "who retracted, when" — and now you've reinvented attribution on the edge anyway.
- **Unrevertable and invisible**. No changelog entry, nothing for the revert machinery to grab.

Another version of this is better, adding provenance on the edge. Edge gains `added_by_actor`, `added_at`, `is_active`, `retracted_by`. However, this would reinvent smaller version of existing systems:

- **Attribution**. Attribution flows through `ChangeSet.actor`; `Claim.actor` is explicitly just a denormalized copy. This approach adds a second, parallel attribution channel that doesn't go through a `ChangeSet`.
- **Revert**. Today revert is per-`ChangeSet` (on the global changelog) or per-`Claim` (on entity's edit history). How do we revert a citation edition? You don't want revert the entire `Claim`. You'd have to add a bespoke path.

### ❌ Rewrite existing data patches

As of July 21 2026, the last data patch ingested on prod was 0038-model-game-formats; we can rewrite any patch after that to include the full set of citations. That wouldn't catch all of them, but it'd catch most.

This might work _THIS_ time, and in fact we'll probably do it in order to have cleaner data -- see [follow ups](#rewrite-existing-data-patches-in-flipcommons) -- but whether we do or not, it's not the long term solution:

- It won't work the next time we want to enhance citations and all these patches have shipped.
- I'd like people to be able to add citations after the fact.

### ❌ Invent new ingest sources for these citation updates

This would suck: it might work this once, but:

- We couldn't use the same ingest source to go back and add more cites to the same fact later.
- It'd require re-asserting a fact that this source shouldn't re-assert.
- It'd create a 'fake' ingestion source rather than showing that the cite was creating by the correct user/ingest source.

## Technical notes

### Pre-refactors

Prerefactors to do in commit(s) BEFORE this plan's main work. All of it goes in the same PR as the plan's main work.

#### change_detail

It sounds like the backend uses `change_detail` to refer to something that should be called `changeset_detail`. Let's rename it to reduce confusion. Semantically a 'change' is closer to a 'claim' not a 'changeset', I want to ensure we there's a bright dividing line between the two.

## Follow-ups

### Rewrite existing data patches in Flipcommons

See [Rewrite existing data patches](#-rewrite-existing-data-patches).

### Citations on entity source page

See [entity source page](#entity-sources).

### Adding citations from entity detail page

See [Entity Detail Page](#entity-record-detail) and [I Agree UI](#an-i-agree-ui).

### Citation instance edit

Add a UI for editing a the `CitationInstance` attached to a claim, but under the hood it would be a remove + add.

## Technical design

TBD
