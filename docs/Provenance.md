# Provenance System

## Two-Layer Architecture

The catalog uses a **claims-based provenance system** with two layers:

1. **Claims layer** — A stream of source-attributed facts. Each claim is a single assertion by a Source (external database, book, editorial team) or User about one field of one catalog entity. Multiple sources can assert different values for the same field.

2. **Resolution layer** — Materialized model fields derived from claims via priority-based conflict resolution. The highest-priority source wins. Resolution is deterministic and repeatable.

Provenance tracks **attribution**, not just disputes. The claims system serves three purposes simultaneously:

1. **Conflict resolution** — When multiple sources assert different values for the same field, the highest-priority source wins. This is deterministic and repeatable.
2. **Audit trail** — Every piece of catalog data has a record of who said it and where it came from, regardless of whether there is any dispute.
3. **Future extensibility** — A field that only has one source today may gain additional sources tomorrow. Claims-based fields accept new sources with zero migrations or re-architecture. Structural fields require re-architecture when a second source arrives.

Every piece of catalog data may eventually come from a different source or user, and the system must always be able to answer "who said this, and where did it come from?"

Slugs are claim-controlled: they are editorially curated values (e.g., which machine gets `breakout` vs `breakout-2` is an explicit editorial decision) and go through the claims system like any other catalog fact.

## Claims

A **Claim** asserts a single fact: "Source X says Entity Y's field Z has value V."

Key properties:

- **Target**: Any catalog entity (via generic foreign key)
- **Attribution**: Exactly one of `source` (external) or `user` (human contributor)
- **Field**: `field_name` identifies what's being claimed (e.g. "name", "production_year", "credit")
- **Claim key**: Uniqueness identifier. For scalar fields this equals the field name. For relationships it encodes the relationship identity by target PK (e.g. `credit|person:42|role:7`)
- **Value**: The asserted data (JSON). FK fields store the target row's integer PK — never its slug — so renaming an entity's slug cannot invalidate claims that reference it. Slugs appear only at authoring boundaries (patch YAML, API payloads) and are resolved to PKs at write time.
- **Superseding**: A new claim from the same source for the same claim key deactivates the old one

### Scalar Claims

Simple field values: name, year, player count, manufacturer (by target PK), etc.

### Relationship Claims

Structured relationships with identity: credits (person + role), themes, tags, gameplay features, abbreviations. Each relationship instance gets its own claim key encoding its identity parts.

## Resolution

Resolution picks a winner per field/claim-key and materializes the result:

- Claims ordered by source priority (descending), then creation date
- Highest-priority source wins
- Scalar winners are coerced to the appropriate field type and set on the model
- Relationship winners are materialized into M2M tables or dedicated records

## ALL user-inputted fields MUST be claims-based

**Every user-inputted catalog field MUST be claims-based**: scalars, FKs, M2M, slugs, parents, aliases. This includes ingested data that goes into fields that users can input.

NOT claims-based: **System-generated fields** like `id`/`uuid`, timestamps, derived fields like `Location.location_path = f"{parent.location_path}/{slug}"`.

## Key Code

- `backend/apps/provenance/models/` — Source, Claim, ChangeSet, IngestRun
- `backend/apps/provenance/claim_writer.py` — `_assert_claim`, the single claim-mint primitive (the one non-ingest place a Claim is persisted)
- `backend/apps/catalog/claims.py` — Relationship schemas and claim key helpers
- `backend/apps/catalog/resolve/` — Resolution logic
