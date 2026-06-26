# Write Path Matrix

Every path that can write catalog truth, as of 2026-03-27.

Columns:

- **Entry point** — where the write originates
- **Writes claims?** — rows created in `provenance_claim`
- **Writes resolved tables?** — scalar fields on catalog model rows (MachineModel, Person, etc.)
- **Writes materialized relationships?** — M2M through-tables, alias tables, credit rows
- **Validation scope** — what is actually checked before the write
- **Bypasses save/full_clean?** — whether ORM bulk operations skip Django's normal validation hooks
- **Post-hoc audit only?** — whether any claim is written after the model row is already updated (claim logs the fact rather than driving it)

---

## Human-interactive paths

| Entry point                                           | Writes claims?                                                         | Writes resolved tables?                                                                               | Writes materialized relationships?                                        | Validation scope                                                                                                                                                                                 | Bypasses save/full_clean?                                                                                                        | Post-hoc audit only?                                                                                                                                                                                                             |
| ----------------------------------------------------- | ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **User edit UI** — `PATCH /api/{type}/{slug}/`        | Yes — `assert_claim()` per changed field via `execute_claims()`        | Yes — `resolve_entity()` / `resolve_model()` calls `obj.save()`                                       | Yes — relationship resolvers (themes, credits, abbreviations, tags, etc.) | **Full** — type coercion, field validators (MinValue/MaxValue/mojibake), markdown link cross-reference, FK/slug existence, cycle detection, duplicate checks                                     | Partial — `validate_scalar_fields()` manually runs field validators; resolve path calls `obj.save()` without `full_clean()`      | No — claims written first; resolution follows                                                                                                                                                                                    |
| **Django admin** — `ProvenanceSaveMixin.save_model()` | Yes — `assert_claim()` for changed claim-controlled scalar fields only | Yes — `super().save_model()` writes model first; `resolve()` overwrites claim-controlled fields after | None — all M2M and alias inlines are read-only                            | **Form + markdown** — Django admin form runs field validators (mojibake, MinValue/MaxValue); `prepare_markdown_claim_value()` called in `save_model()`; NO FK/slug existence, NO cycle detection | Partial — admin form is form-level validation, not model `full_clean()`; claim write + resolve path does not call `full_clean()` | **Yes — but safe** — `super().save_model()` writes model first, claim asserted after, resolve re-applies; whole sequence is inside Django's `changeform_view` `transaction.atomic()`, so a resolve failure rolls everything back |

---

## Automated ingest — claim-based writes

| Entry point                                                                                                                                                            | Writes claims?                      | Writes resolved tables?              | Writes materialized relationships? | Validation scope                                                                                                                                                 | Bypasses save/full_clean?                                  | Post-hoc audit only?                                          |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------- | ------------------------------------ | ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- | ------------------------------------------------------------- |
| **All ingest commands** → `bulk_assert_claims()` (`ingest_ipdb`, `ingest_opdb`, `ingest_pindata`, `ingest_wikidata`, `ingest_wikidata_manufacturers`, `ingest_fandom`) | Yes — `bulk_create()` of Claim rows | No — separate resolve call follows   | No — separate resolve call follows | **Mojibake only** — `validate_no_mojibake()` on string claim values; no field range validators, no markdown cross-reference, no FK existence, no cycle detection | Yes — `bulk_create()` bypasses `save()` and `full_clean()` | No — claims written first; resolve is called explicitly after |
| **`scrape_images`** → `assert_claim()` for `image_urls`                                                                                                                | Yes — single claim per image URL    | Yes — `resolve_model()` called after | No                                 | **None** — no validation on URL format or content                                                                                                                | No — `assert_claim()` uses `Claim.objects.create()`        | No — claim written first; resolution follows                  |

---

## Automated ingest — direct ORM bypass writes (no claims)

These paths write to catalog tables without creating a claim. There is no audit trail.

`series.titles.add()` confirmed as the **only** non-claim M2M write in production code (verified by full-codebase grep — all other `.add()` calls are Python `set.add()`).

| Entry point                                                                                                         | Writes claims?                                    | Writes resolved tables?                                             | Writes materialized relationships?              | Validation scope                                                                                                               | Bypasses save/full_clean?                                  | Post-hoc audit only?                      |
| ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- | ------------------------------------------------------------------- | ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------- | ----------------------------------------- |
| **`ingest_pindata`** — `series.titles.add(*titles)` (line 1560)                                                     | **No**                                            | No                                                                  | **Yes — directly writes series-title M2M rows** | **None**                                                                                                                       | Yes — `.add()` bypasses `save()` and `full_clean()`        | **N/A — no claim ever created**           |
| **`ingest_wikidata`** — `person.save(update_fields=["wikidata_id", "updated_at"])` (line 143)                       | **No**                                            | **Yes — writes `wikidata_id` directly to Person**                   | No                                              | **None** — `update_fields` bypasses `full_clean()` and field validators                                                        | Yes — `update_fields` skips `full_clean()`                 | **N/A — no claim ever created**           |
| **`ingest_wikidata_manufacturers`** — `mfr.save(update_fields=["wikidata_id", "updated_at"])` (line 162)            | **No**                                            | **Yes — writes `wikidata_id` directly to Manufacturer**             | No                                              | **None**                                                                                                                       | Yes                                                        | **N/A — no claim ever created**           |
| **`ingest_ipdb`** — `ce.save(update_fields=["ipdb_manufacturer_id"])` (line 681)                                    | **No**                                            | **Yes — writes `ipdb_manufacturer_id` directly to CorporateEntity** | No                                              | **None**                                                                                                                       | Yes                                                        | **N/A — no claim ever created**           |
| **`ingest_pindata`** — `Title.objects.filter().update(slug=...)` / `.update(fandom_page_id=...)` (lines 1547, 1551) | **No**                                            | **Yes — writes `slug` and `fandom_page_id` directly to Title**      | No                                              | **None** — `QuerySet.update()` bypasses all validation                                                                         | Yes — `QuerySet.update()` bypasses `save()` entirely       | **N/A — no claim ever created**           |
| **`ingest_pindata`** — `MachineModel.objects.bulk_update([...], ["created_at", "model_slug"])` (line 1683)          | **No**                                            | **Yes — writes `created_at` and `model_slug` to MachineModel**      | No                                              | **None**                                                                                                                       | Yes                                                        | **N/A — no claim ever created**           |
| **All bootstrap ingest** — `bulk_create_validated(MachineModel, ...)` / `bulk_create_validated(Location, ...)` etc. | No — this creates catalog object rows, not claims | **Yes — creates new catalog model rows**                            | No                                              | **Mojibake only** — `validate_no_mojibake()` runs before `bulk_create()`; no field range validators, no markdown, no FK checks | Yes — `bulk_create()` bypasses `save()` and `full_clean()` | N/A — object bootstrap, not a claim write |

---

## Resolution / materialization sub-system

Called by all of the above after claim writes. Not an independent entry point, but a distinct write layer.

| Entry point                                                                                                      | Writes claims?    | Writes resolved tables?                      | Writes materialized relationships?                                                                                                      | Validation scope                                     | Bypasses save/full_clean?                                  | Post-hoc audit only?                   |
| ---------------------------------------------------------------------------------------------------------------- | ----------------- | -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- | ---------------------------------------------------------- | -------------------------------------- |
| **`resolve_entity()` / `resolve_model()`** (single-entity, called from API + admin + ingest)                     | No — reads claims | Yes — `obj.save()` for scalar fields         | Yes — calls relationship resolvers                                                                                                      | **None** — projects winning claims; no re-validation | Partial — calls `obj.save()` without `full_clean()`        | N/A — reads claims, doesn't write them |
| **`resolve_entities_bulk()` / `resolve_all_entities()`** (bulk, called from the ingest apply engine)             | No — reads claims | Yes — `model_class.objects.bulk_update(...)` | Yes — calls bulk relationship resolvers                                                                                                 | **None**                                             | Yes — `bulk_update()` bypasses `save()` and `full_clean()` | N/A                                    |
| **`_resolve_machine_model_m2m()`, `resolve_all_credits()`, `_resolve_aliases()`** (relationship materialization) | No — reads claims | No                                           | Yes — `through.objects.delete()` + `through.objects.bulk_create()`; `alias_model.objects.bulk_create()`; `Credit.objects.bulk_create()` | **None**                                             | Yes — `bulk_create()` and `.delete()` bypass `save()`      | N/A                                    |

---

## Summary observations

### Validation coverage by path

| Path                               | Field validators | Markdown cross-ref   | FK/slug existence | Cycle detection | Mojibake       |
| ---------------------------------- | ---------------- | -------------------- | ----------------- | --------------- | -------------- |
| User edit API                      | Yes              | Yes                  | Yes               | Yes             | Yes            |
| Django admin                       | Yes (via form)   | Yes (via save_model) | No                | No              | Yes (via form) |
| `bulk_assert_claims()`             | No               | No                   | No                | No              | Yes            |
| `scrape_images` → `assert_claim()` | No               | No                   | No                | No              | No             |
| All direct ORM bypass writes       | No               | No                   | No                | No              | No             |
| Resolution sub-system              | No               | No                   | No                | No              | No             |

### Fields with no claim (direct ORM bypass writes)

Every model uses `slug` as its slug field name — there are no exceptions.

Fields are either written without claims because they are explicitly declared `claims_exempt` on the model (a deliberate prior AI decision), or because they are true infrastructure fields.

#### Explicitly declared `claims_exempt` — all to be removed

Policy (settled): **every field set by a human or data source requires a claim.** The only legitimate exemptions are fields set exclusively by the database engine itself (`id`/`uuid`, `created_at`, `updated_at`). "Single source today", "structural", and "derived from another field" are not valid exemptions.

Specific notes:

- `wikidata_id`, `ipdb_manufacturer_id`, `fandom_page_id` — audit trail: need to know who set them and when.
- `needs_review`, `needs_review_notes` — both audit trail **and** conflict resolution: a higher-priority source/user must be able to assert `needs_review=False` and win over an ingest-sourced `True`. Without claims there is no priority weighting and a re-ingest can silently overwrite a human's review decision.
- `technology_generation` on `TechnologySubgeneration`, `display_type` on `DisplaySubtype`, `manufacturer`/`technology_subgeneration` on `System` — taxonomy parent FKs; audit trail requires knowing who assigned the parent and when.
- `slug` — generated by code from a `name` claim, but code acts on behalf of a source/user; who triggered the slug and when should be recorded.

| Field                                                             | Model                     | Declared in           | Written by (direct ORM)                                       |
| ----------------------------------------------------------------- | ------------------------- | --------------------- | ------------------------------------------------------------- |
| `wikidata_id`                                                     | `Person`                  | `person.py:27`        | `ingest_wikidata` → `save(update_fields=[...])`               |
| `wikidata_id`, `opdb_manufacturer_id`                             | `Manufacturer`            | `manufacturer.py:37`  | `ingest_wikidata_manufacturers` → `save(update_fields=[...])` |
| `manufacturer`, `ipdb_manufacturer_id`                            | `CorporateEntity`         | `manufacturer.py:103` | `ingest_ipdb` → `ce.save(update_fields=[...])`                |
| `opdb_id`, `fandom_page_id`, `needs_review`, `needs_review_notes` | `Title`                   | `title.py:25-32`      | `ingest_pindata` → `bulk_update(["fandom_page_id"])`          |
| `technology_generation`                                           | `TechnologySubgeneration` | `taxonomy.py:69`      | (FK, written via admin form + resolve)                        |
| `display_type`                                                    | `DisplaySubtype`          | `taxonomy.py:131`     | (FK, written via admin form + resolve)                        |
| `manufacturer`, `technology_subgeneration`                        | `System`                  | `system.py:22`        | (FKs, written via admin form + resolve)                       |
| `location_path`                                                   | `Location`                | `location.py:31`      | (computed path, written in ingest)                            |

#### Bootstrap ORM writes before claims are asserted

`MachineModel` has no `claims_exempt`. These writes happen during bootstrap (before `bulk_assert_claims` runs for the same ingest pass), so claims catch up immediately after:

| Field                | Model          | Written by                                               |
| -------------------- | -------------- | -------------------------------------------------------- |
| `opdb_id`, `ipdb_id` | `MachineModel` | `ingest_pindata` → `bulk_update(["opdb_id", "ipdb_id"])` |
| `opdb_id`            | `MachineModel` | `ingest_opdb` → `bulk_update(["opdb_id"])`               |

#### Infrastructure (legitimately exempt)

| Field                      | Model      | Reason                                                  |
| -------------------------- | ---------- | ------------------------------------------------------- |
| `created_at`, `updated_at` | All models | Set by the database engine, never by a human or source. |

`slug` is **not** exempt. Slugs are editorially curated in pindata (e.g. which machine gets `breakout` vs `breakout-2` is an explicit editorial decision), written by ingest with flipcommons-catalog as source, and changeable by admins. They must be claim-controlled.

#### No-claim M2M write

| Relationship            | Written by                                      | Status                                                                                                             |
| ----------------------- | ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Series-title membership | `ingest_pindata` → `series.titles.add(*titles)` | **Must become claim-controlled** — which titles belong to a series is an editorial decision requiring audit trail. |

### The admin inversion

The admin path is the only human-interactive path where the model row is written _before_ the claim. `super().save_model()` persists the Django model, then `assert_claim()` records what changed, then `resolve()` re-applies it. Claims are not the gatekeeping mechanism here — they are a record of what the admin user did.

### Resolution has no validation budget

Every resolved scalar and every materialized relationship row is written by bulk operations that bypass `save()` and `full_clean()`. If an invalid value enters via a claim, resolution will materialize it without complaint.
