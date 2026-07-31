# Export-market models

This is a proposal to add more structure around how the product represents models built for export to another market.

## Status

The schema and product surfaces shipped on `feat/export-editions`:

1. ✅ DONE: **`export_edition_of`** — scalar lineage FK on `MachineModel` (PROTECT, anti-self CHECK, claims-based via the generic scalar-FK path). Subordinates in `first_model_candidates()` (the Big Ben rule — an export edition never outranks its domestic original when they share a Title), joins the cross-title related-titles collector, the model detail schema (`export_edition_of` + reverse `export_editions`), the bulk-export dump, the related-models editor (an "Export edition of" kind) and the "Export Edition" display section.
2. ✅ DONE: **`ModelExportMarket`** — claim-controlled join table (namespace `export_market`), identity = nullable `target_market_location`, non-identity `target_market_label`. Two spec extensions carry its shape generically: `MemberXor.required=False` (an _optional_ XOR — the all-absent row is the legal unknown-market shape; patch syntax `- {}`) and `MemberField.target_filter` (pure-data target restriction — `COUNTRY_TARGET_FILTER` limits locations to countries across resolution, batch validation, the patch adapter and the editor planner). The "a null-location row must be the model's only row" rule is enforced in the editor planner and per-entry in the patch adapter (generically, keyed off the optional-XOR spec shape — a cross-patch mix still needs a `remove:` of the null-location row first); the DB carries the per-rung UNIQUEs and the at-most-one CHECK (the cross-row mix rule isn't expressible without triggers). Display: folded into the single "Export Edition" section, which states the goal sentence — "This model is the export version of X, built for export to Y and Z" — dropping either half when unknown (an unknown-market row shows no market rather than "Unknown market"); editing: an "Export markets" block in the related-models editor. Locations targeted by a market row are delete-blocked via the `export_market_models` usage blocker.
3. **`export` tag deletion** — the docs no longer mention it (DomainModel.md); the `Tag` row's `delete:` ships as a flippatch data patch (it has zero memberships, so no membership sweep is needed).

Remaining: the data patches themselves (the review buckets below), authored in flippatch per the [shipping plan](../ModelRelationships.md#rework-but-dont-ship-the-data-patches).

## Problem statement

Some pinball models are built specifically to serve a foreign market. They usually differ in `reward_type`: an add-a-ball or novelty edition of a replay/payout game, built for a jurisdiction that did not allow the original's reward type (Italy, France, Germany, Spain…).

Today the catalog data carries this information in inconsistent ways:

- an `export` tag that is not used once, not a single time
- a `(Country)` suffix baked into the name
- freetext prose from IPDB in `extra_data` (not shown in the UI at all)
- and mostly not at all

We want to represent these relationships in a consistent, structured way, so that:

- The website can say a clear sentence like "This model is the export version of [other model], built for export to [market(s)]."
- We can see the inconsistencies and fix them
- For research purposes we can run queries and find export models

## Product Proposal

### 🆕 `export_edition_of`

Add a `MachineModel.export_edition_of` field to represent a model being an export edition of another model.

This is a singular relationship -- don’t try to represent this in the `ModelRelationships` join table -- because:

- A model can only be an export edition of a single other model.
- An export is always legal, so licensing doesn't apply. If it's not authorized, then it's an unlicensed copy, not an export.

A model can set both `export_edition_of` **AND** other relationhsips, like `variant_of` or a `ModelRelationship` relationship type of `copy`. Usually but not always to the same target model.

We considered an alternative where we didn't have `export_edition_of`, but intsead required `variant_of` and `copy` to carry the relationship. That doesn't work because in the VAST MAJORITY of cases (data below) the only relationship info we know is that model X is the export version of model Y; we don't know whether it's gameplay-identical (a variant) or not. So the only honest thing we can say about the relationship is that it's `export_edition_of`.

If we don't know the model of which it is an export, we don't set the relationship. Instead we rely entirely on the [model export location join table](#-model-export-location-join-table).

### 🆕 model export location join table

Add a join table of model to location called `ModelExportMarket`.

- It's a join table because a model can be made for export to multiple countries / markets.
  - There's less than 5 models, less than 2% of the export models, that have more than one export location.
- There are TWO target fields `target_market_location` or `target_market_label`.
- The `target_market_location` can only be a country, i.e. Locations that have no parent.
- If it's for export to a region like Europe and not a country, leave `target_market_location` null and set `target_market_label` to something like “Europe”.
  - There's less than 10 of these, less than 2% of the export models.
- If we don't know anything about the export location, we null both `target_market_location` AND `target_market_label`.
  - There's more than 100 of these, about half of the export models.
- A model can have either:
  - multiple rows with target_market_locations
  - a single row with a nonblank label
  - a single row with a null for both target fields

Another way of saying that: a row with a NULL target_market_location must be the model's only row.

### Predicate for determining whether a model is for export

Something like: `export_edition_of IS NOT NULL OR EXISTS(ModelExportMarket row)`.

We considered just `EXISTS(ModelExportMarket row)`, but we will not autocreate a ModelExportMarket row when a user creates a export_edition_of; what would we put it in? We won't know what to put in it.

### ❌ `export` tag

Delete the `export` tag. It exists as a `Tag` row (slug `export`) but has never been applied. Zero of our 6,915 models carry it. It's dead weight to retire alongside the composite tags in [ModelRelationships.md → step 9](ModelRelationships.md#migration-map).

## Data

The analysis of models for export lives in **flippatch**, at [`campaigns/0177-exports/`](../../../../../flippatch/campaigns/0177-exports/) — DuckDB views over the live catalog, alongside the data-patch campaign that acts on them. Flippatch wholly owns it: how to run it, what the detectors are, and how the candidates decompose into review buckets are all documented in that directory's README, which is where they stay current. This doc specifies the two catalog structures; it does not duplicate the data work.
