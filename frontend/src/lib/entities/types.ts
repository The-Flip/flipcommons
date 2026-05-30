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
 * A reference to an external system
 */
export type ExternalReference =
  /** A linkable reference */
  | {
      /** Display label for hyperlinks to the external system */
      label: string;
      /** `{id}` is replaced by the stored value to generate a URL */
      urlTemplate: string;
    }
  /** A non-linkable reference */
  | {
      /** An ID of the thing in the external system that does not correspond to any URL. In JSON-LD, this is emitted as a schema.org `PropertyValue` (`propertyID` ← `identifier`). */
      identifier: string;
    };

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

  /** The schema.org schemas this entity maps to */
  schemaOrg: SchemaOrgInfo<TSchema>;

  /**
   * External-database references keyed by API field name — the single place
   * each external site's label and URL is defined. Feeds both the visible
   * "External Links" UI (via `externalLinks()`) and the JSON-LD
   * `sameAs`/`identifier` (via `buildSchemaOrgNode`), so components render
   * links from here instead of hardcoding URLs in markup.
   * See {@link ExternalReference}.
   */
  externalRefs?: Partial<Record<keyof TSchema, ExternalReference>>;
}
