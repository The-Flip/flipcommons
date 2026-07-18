# Export-market models

This is a proposal to add more structure around how the product represents models built for export to another market.

## Problem statement

Some pinball machine models are built specifically to serve a foreign market. They usually differ in `reward_type`: an add-a-ball or novelty edition of a replay/payout game, built for a jurisdiction that did not allow the original's reward type (Italy, France, Germany, Spain…).

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

The analysis of models for export lives in [`exports.sql`](exports.sql). It's DuckDB views over the live catalog. How to run it is in that file's header comment.

It decomposes the candidates into review buckets, each a first-guess worklist for a data patch:

`export_edition_of`:

- `export_twin_pairs`: deterministic `export_edition_of` target Model
- `export_titlemate_review`: the likely `export_edition_of` target Model is sitting the same Title.
- `export_orphan_review`: candidates still needing a target

`ModelExportMarket`:

- `export_market_review`: which `ModelExportMarket` shape each candidate takes
