import type { RichTextSchema } from '$lib/api/schema';
import { ENTITY_META, type EntityRelationship } from '$lib/entities/entity-meta';
import { jsonLdGraph, breadcrumbList, absolutize, type JsonLdNode } from '$lib/components/jsonld';
import type { EntityInfo } from './types';

/**
 * The minimal entity facts every schema.org node needs. Widens in a later
 * tranche (external IDs / `sameAs`).
 *
 * `public_id` is the entity's uniform URL identity (`slug` for most entities,
 * `location_path` for Location) — the backend twin of `LinkableDetailSchema`.
 * The `@id` is built from it, never from `slug`.
 */
export interface EntityBaseFacts {
  name: string;
  public_id: string;
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

  // fieldMap: copy scalar API fields to their schema.org property names.
  // Iterate the map's own keys (not Object.entries, which widens the key to
  // `string` and breaks the typed `entity[key]` read).
  const fieldMap: Partial<Record<keyof T, string>> = info.schemaOrg.fieldMap ?? {};
  for (const key of Object.keys(fieldMap) as (keyof T)[]) {
    const targetProp = fieldMap[key];
    if (targetProp === undefined) continue;
    const value = entity[key];
    if (value === null || value === undefined || value === '') continue;
    node[targetProp] = value;
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

  return node;
}

/**
 * Build the full `@graph` for an entity detail page: the entity node plus a
 * `Home › {name}` breadcrumb. The listing page is omitted from the trail
 * because it's CSR/non-crawlable.
 */
export function buildEntityJsonLd<T extends EntityBaseFacts>(
  entity: T,
  info: EntityInfo<T>,
  pageUrl: URL,
): Record<string, unknown> {
  return jsonLdGraph([
    buildSchemaOrgNode(entity, info, pageUrl),
    breadcrumbList(pageUrl, [{ label: 'Home', href: '/' }], entity.name),
  ]);
}
