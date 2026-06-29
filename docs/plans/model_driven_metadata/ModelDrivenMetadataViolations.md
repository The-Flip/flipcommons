# Model-Driven Metadata — Violations

Hand-maintained registries / maps that duplicate information Django already knows, per the criteria in [ModelDrivenMetadata.md](ModelDrivenMetadata.md). This doc has two layers: the raw inventory (one row per active violation) and a grouping of those rows by consuming subsystem into analytical clusters.

Current count: **one active violation**.

## Findings: one cluster

The single remaining active violation.

### Cluster 1 — Citation source identity (1 of 1)

The `identifier_key` touch-points (extractor dict, Django enum, CHECK constraint). One axis, subsumed by `CitationSourceSpec`.

Detailed design — the consumers, the open ownership question, the migration-story caveat for the CHECK constraint, and the dependency on `CatalogRelationshipSpec` — lives in [ModelDrivenCitationSourceMetadata.md](ModelDrivenCitationSourceMetadata.md).

## Inventory

| Name                          | Location(s)                                                                                                                                                                                                        | What it duplicates                                                                  | Consuming subsystem                               | Frequency | Blast radius | Fix cost | Notes                                                                                                                                                                                                                                                                                 |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------- | ------------------------------------------------- | --------- | ------------ | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `identifier_key` touch points | `backend/apps/citation/extractors.py:66` (`EXTRACTORS`), `backend/apps/citation/models.py:138-148` (`IdentifierKey` TextChoices + field), `backend/apps/citation/models.py:219-222` (`identifier_key_valid` CHECK) | Enum values and CHECK constraint values duplicate the keys of the `EXTRACTORS` dict | URL recognition (`recognize_url`) + DB validation | 1         | 2            | M        | Flagged by memory note `project_identifier_key_stopgap`. Three touch points today; items 2 and 3 could be derived from `EXTRACTORS` keys. Current set is small (ipdb, opdb, youtube) but the drift risk is the asymmetric "add to extractor, forget the enum and CHECK" failure mode. |

## Notes on excluded candidates

- `LinkType` registry (`core/markdown_links.py`) — populated from model class attrs (`link_label`, `link_sort_order`, …) in `CatalogConfig.ready()`. Correct "class-attr + derivation" shape; key-naming convergence with `_ENTITY_TYPE_MAP` (both keying on `entity_type` rather than this registry's current `__name__.lower()`/`link_type_name` fallback) lands with [ModelDrivenWikilinkableMetadata.md](ModelDrivenWikilinkableMetadata.md).
- `_ENTITY_TYPE_MAP` (`core/entity_types.py`) — derived from `LinkableModel` subclasses. Listed in the parent doc as the canonical example.
- IPDB `CLAIM_FIELDS` / `CREDIT_FIELDS`, `IPDB_TAG_MAP`, `PROP_TO_ROLE`, `_LABEL_TO_ROLE`, `_COUNTRY_NORMALIZATION`, `_STATE_NORMALIZATION` — source-specific translation tables (external-name → internal-slug). Not duplicates of Django model metadata.
- `MEDIA_CATEGORIES`, `claim_fk_lookups`, `claims_exempt`, `soft_delete_cascade_relations`, `soft_delete_usage_blockers`, `api_type_key` — already on model classes as the correct pattern.
- Manufacturer / corporate-entity lookup dicts in `bulk_utils.py` — in-function caches populated from DB queries, not hand-maintained metadata.
- Rate-limit constants, media dimension constants, licensing ranks — module-level configuration orthogonal to any specific model.
- Ninja router autodiscovery (`config/api.py`) — framework contract.
