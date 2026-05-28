import type { CatalogEntityKey } from '$lib/models/model-meta';

/**
 * Per-model schema.org presentation declarations. Lives frontend-side because
 * schema.org type/property names are vocabulary the backend never consumes
 * (see docs/plans/seo/JsonLdAndFriends.md, "Why frontend assembly").
 */
export interface SchemaOrgInfo<TSchema> {
  /**
   * The schema.org `@type`(s) for this entity — a static list, or a per-row
   * function when the type depends on entity data (e.g. Location).
   */
  types: readonly string[] | ((entity: TSchema) => readonly string[]);
  /** Maps API field names → schema.org property names. Not consumed yet. */
  fieldMap?: Partial<Record<keyof TSchema, string>>;
  /** Maps API FK/M2M field names → schema.org property names. Not consumed yet. */
  relationshipMap?: Partial<Record<keyof TSchema, string>>;
}

/**
 * The frontend companion to a Django catalog model: presentation declarations
 * the backend doesn't need. One file per model under `$lib/models/`.
 */
export interface ModelFrontendInfo<TSchema> {
  /** The CATALOG_META key (`entity_type`), e.g. 'theme' — NOT the export name. */
  entityType: CatalogEntityKey;
  schemaOrg: SchemaOrgInfo<TSchema>;
}
