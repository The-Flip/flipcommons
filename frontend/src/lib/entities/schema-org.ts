import type { RichTextSchema } from '$lib/api/schema';
import { ENTITY_META, type EntityRelationship } from '$lib/entities/entity-meta';
import {
  jsonLdGraph,
  breadcrumbList,
  absolutize,
  type JsonLdNode,
  type Crumb,
} from '$lib/components/jsonld';
import type { EntityInfo, ExternalReference, FieldMapEntry } from './types';

/**
 * Entity facts shared by every schema.org node.
 */
export interface EntityBaseFacts {
  name: string;
  /** For most entities this will be its slug.  For Location it'll be its location_path. */
  public_id: string;
  /** ISO 8601 freshness timestamp, same value as sitemap `<lastmod>` */
  last_modified: string;
  description: RichTextSchema;
}

/** The minimal shape of a relationship referent: refs ship `{ name, public_id }`. */
interface RefLike {
  public_id: string;
}

/**
 * Build the schema.org node for a single catalog entity: `@type`, a canonical
 * `@id`, `name`, and an untruncated `description` (the backend's flattened
 * `description.plain`). The `@id` is the entity's canonical URL
 * (`/{entity_type_plural}/{public_id}`), independent of the current path — so
 * it's stable even when the layout load runs on a sub-route.
 */
export function buildSchemaOrgNode<T extends EntityBaseFacts>(
  entity: T,
  info: EntityInfo<T>,
  pageUrl: URL,
): JsonLdNode {
  const typeSpec = info.schemaOrg.types;
  const types = typeof typeSpec === 'function' ? typeSpec(entity) : typeSpec;
  const meta = ENTITY_META[info.entityType];
  const node: JsonLdNode = {
    '@type': types.length === 1 ? types[0] : [...types],
    '@id': absolutize(pageUrl, `/${meta.entity_type_plural}/${entity.public_id}`),
    name: entity.name,
  };
  const desc = entity.description.plain.trim();
  if (desc) node.description = desc;

  // dateModified is universal (every catalog entity is TimeStamped), so it's
  // emitted directly here rather than declared in each per-model fieldMap. The
  // value is the sitemap's `<lastmod>` (ISO 8601), already date-shaped — no
  // coercion, unlike the fieldMap value transforms.
  if (entity.last_modified) node.dateModified = entity.last_modified;

  // fieldMap: copy scalar API fields to their schema.org property names,
  // applying any declared value transform. Iterate the map's own keys (not
  // Object.entries, which widens the key to `string` and breaks the typed
  // `entity[key]` read).
  const fieldMap: Partial<Record<keyof T, FieldMapEntry>> = info.schemaOrg.fieldMap ?? {};
  for (const key of Object.keys(fieldMap) as (keyof T)[]) {
    const entry = fieldMap[key];
    if (entry === undefined) continue;
    const value = entity[key];
    if (value === null || value === undefined || value === '') continue;
    const { property, transform } =
      typeof entry === 'string' ? { property: entry, transform: undefined } : entry;
    // `transform: 'year'` coerces an int year (e.g. 1992) to a partial ISO
    // date string ("1992") that schema.org date properties accept.
    node[property] = transform === 'year' ? String(value) : value;
  }

  // relationshipMap: emit cross-reference `@id`s for FK/M2M fields.
  const relationshipMap: Partial<Record<keyof T, string>> = info.schemaOrg.relationshipMap ?? {};
  const rels: Readonly<Record<string, EntityRelationship>> = meta.relationships;
  for (const field of Object.keys(relationshipMap) as (keyof T)[]) {
    const property = relationshipMap[field];
    if (property === undefined) continue;
    const rel = rels[field as string];
    if (rel === undefined) {
      throw new Error(
        `relationshipMap for '${info.entityType}' maps '${String(field)}' to '${property}', but it is not a declared relationship`,
      );
    }
    const raw = entity[field];
    const list: readonly unknown[] = Array.isArray(raw) ? raw : [raw];
    const refs = list.filter((ref): ref is RefLike => ref !== null && ref !== undefined);
    if (refs.length === 0) continue;
    const targetPlural = ENTITY_META[rel.entity_target_type].entity_type_plural;
    const ids = refs.map((ref) => ({
      '@id': absolutize(pageUrl, `/${targetPlural}/${ref.public_id}`),
    }));
    node[property] = rel.many ? ids : ids[0];
  }

  // externalRefs: the same registry that drives the visible "External Links" UI
  // (see external-links.ts) feeds the open-linked-data identities here. Resolvable
  // entries become `sameAs` URLs; non-resolvable ones become `identifier`
  // PropertyValues. External URLs bypass absolutize() — that discipline is for
  // internal `@id`s only.
  const externalRefs: Partial<Record<keyof T, ExternalReference>> = info.externalRefs ?? {};
  const sameAs: string[] = [];
  const identifiers: JsonLdNode[] = [];
  for (const key of Object.keys(externalRefs) as (keyof T)[]) {
    const entry = externalRefs[key];
    if (entry === undefined) continue;
    const value = entity[key];
    if (value === null || value === undefined || value === '') continue; // same skip rule as fieldMap
    if ('urlTemplate' in entry) {
      sameAs.push(entry.urlTemplate.replace('{id}', String(value)));
    } else {
      identifiers.push({
        '@type': 'PropertyValue',
        propertyID: entry.identifier,
        value: String(value),
      });
    }
  }
  // Always arrays → byte-stable, declaration-ordered output (cache-friendly @graph).
  if (sameAs.length) node.sameAs = sameAs;
  if (identifiers.length) node.identifier = identifiers;

  return node;
}

/**
 * Build the full `@graph` for an entity detail page: the entity node plus a
 * breadcrumb. `crumbs` is the trail leading up to (but not including) this
 * page; it defaults to `[Home]` because most listing pages are
 * CSR/non-crawlable. Entities with an SSR parent chain (Model → its Title,
 * Location → its ancestors) pass a richer trail.
 */
export function buildEntityJsonLd<T extends EntityBaseFacts>(
  entity: T,
  info: EntityInfo<T>,
  pageUrl: URL,
  crumbs: Crumb[] = [{ label: 'Home', href: '/' }],
): Record<string, unknown> {
  return jsonLdGraph([
    buildSchemaOrgNode(entity, info, pageUrl),
    breadcrumbList(pageUrl, crumbs, entity.name),
  ]);
}
