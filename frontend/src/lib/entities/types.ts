import type { EntityKey } from '$lib/entities/entity-meta';

/**
 * A `fieldMap` target: either a bare schema.org property name (identity copy)
 * or a tagged form that also applies a named value coercion. The author who
 * writes `year → releaseDate` knows `year` is a date-year, so the intent is
 * encoded locally rather than via a global property-name registry that would
 * drift. `transform` is a typed union, so a typo fails at compile time.
 */
export type FieldMapEntry = string | { property: string; transform: 'year' };

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
  /** Maps API field names → schema.org property names (optionally with a value transform). */
  fieldMap?: Partial<Record<keyof TSchema, FieldMapEntry>>;
  /** Maps API FK/M2M field names → schema.org property names (emitted as `@id` cross-references). */
  relationshipMap?: Partial<Record<keyof TSchema, string>>;
}

/**
 * The frontend companion to a Django linkable entity: presentation declarations
 * the backend doesn't need. One file per entity under `$lib/entities/`.
 */
export interface EntityInfo<TSchema> {
  /** The ENTITY_META key (`entity_type`), e.g. 'theme' — NOT the export name. */
  entityType: EntityKey;
  schemaOrg: SchemaOrgInfo<TSchema>;
}
