# Model: project date

Up to this point, models have have one single date attached to it, which we've used as the date of manufacture. Let's add a new one: Project Date.

Here's the definition of the two date fields:

- **Project Date**: the date when the game's design was finalized, logged in internal corporate documentation, or approved/released to production by the manufacturer. Sometimes called the Release-to-Production Date in internal company archives. Also sometimes referred to as the Design Date.
- **Production Date**: the date of physical assembly and factory rollout.

## Two fields

Like production date, this will be two fields:

- `project_year` — PositiveSmallIntegerField, nullable, range 1800–2100 (catalog_machinemodel_year_range)
- `project_month` — PositiveSmallIntegerField, nullable, range 1–12 (catalog_machinemodel_month_range)

## Validation

- **Not required**. Like production date, project date is not required.
- **Month requires year**. Like production date, enforce that month can only be set when year is set. This is a cross-field constraint (catalog_machinemodel_month_requires_year).
- **Not later than production date**. The project date can never be after the production date. Validate this at the DB level. If either month is null, don't compare months.

## Migration

Project date will start out life empty; all the existing dates in the database are production dates.

## Project date is claim-controlled

Project date is claim-controlled, just like production date.

## Rename production date

At the same time, we will rename the existing `year` and `month` fields to `production_year` and `production_month`.

Let's clean this up completely: do not leave secondary fields or comments hanging around that say 'year' when they mean 'production_year'.

### Existing claims

This will affect existing claims -- things like the field name 'year' is `Claim.field_name`. They'll have to be migrated.

### Data patches

We will not migrate data patches or provide any support for the legacy name of production date. All ingested data patchs are immutable and cannot be replayed. All uningested data patches will have to use the new names. Dev databases are refreshed from the prod db -- we don't replay patches on dev to 'catch up' to prod.

## UX

### Edit UX

Model Basics editor

```text
Title               Manufacturer
[――――     ▼]        [――――     ▼]

Production date
Year                Month
[         ◆]        [――――     ▼]

Project date
Year                Month
[         ◆]        [――――     ▼]

Game format         Production status
[――――     ▼]        [――――     ▼]
```

### Display UX

**Fall back to project date**. Wherever we display model's date like `Godzilla (Stern 2021)`, prefer production date but fall back to project date. In the sidebar we sometimes show the year as a disambiguator like `Godzilla (70th Anniversary) (2024)`, this applies to that too.

**Don't display as standalone field**. We don't currently display the year or month as a standalone field on the detail page, neither in the sidebar or main content area. We will continue displaying neither date.

### Sorting and filtering

The fallback to project date applies to sorting, filtering, aggregation. Currently, `year` is the sort key everywhere (recent-models feed, series order, title first-model tiebreak, manufacturer facets, year_min/year_max filters, corporate-entity year spans).

I'm assuming this will be some sort of synthetic / computed / derived properties on the Django model, presuably called `year` and `month`. Ideally all those sorts and filters "just keep working".

## Analytics

In the analytics foundation, a model will need derived `year` and `month` fields that do the same fallback. Those fields will be used on most later views that need the model's year and month. Since they're the same field names as before, I'd hope that most views 'just work'?

## Export API

Return project date, production date and the derived `year` and `month`.

## Derived date

- **Derive `month` pairwise**: `production_year` set → `production_month`, else `project_month`. Otherwise it could pair production's 2021 with project's June.
- **NOT Claim-controlled**. `year` and `month` must be excluded from Claims control.
- **Read-only**. `year` and `month` become read-only, so every test fixture doing `make_machine_model(year=1997)` (LOTS of them) **must** say `production_year=`. But we were already going to rename them.
