import type { RichTextSchema } from '$lib/api/schema';
import {
  ENTITY_META,
  type CatalogEntityKey,
  type EntityRelationship,
} from '$lib/entities/entity-meta';
import {
  jsonLdGraph,
  breadcrumbList,
  pageNode,
  absolutize,
  type JsonLdNode,
  type Crumb,
} from '$lib/components/jsonld';
import { ENTITY_INFO } from './index';
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
 * page. The default is `[Home]` for callers that have no richer hierarchy;
 * catalog detail layouts usually pass `detailCrumbs(...)` so their breadcrumb
 * routes through the entity's indexable listing page.
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

/**
 * The resolved listing-page copy for a catalog entity: the entity's `listing`
 * copy, falling back to its plural label / a generic description. `title` is
 * the SEO/`<meta>` label; `heading` is the visible `<h1>` (defaults to
 * `title`); `breadcrumb` is the listing's crumb in detail-page breadcrumb
 * trails (defaults to `heading`). The one place these — and the shared
 * subtitle / `<meta>` / JSON-LD description — are derived, so they can't drift.
 */
export function listingMeta(catalogKey: CatalogEntityKey): {
  title: string;
  heading: string;
  breadcrumb: string;
  description: string;
} {
  const meta = ENTITY_META[catalogKey];
  const listing = ENTITY_INFO[catalogKey].listing;
  const title = listing?.title ?? meta.label_plural;
  const heading = listing?.heading ?? title;
  return {
    title,
    heading,
    breadcrumb: listing?.breadcrumb ?? heading,
    description: listing?.description ?? `${meta.label_plural} in the Flipcommons pinball catalog.`,
  };
}

/**
 * Build the `@graph` for a catalog listing page: a `CollectionPage` node whose
 * `mainEntity` is an `ItemList` of the page's items (named, `@id`-referenced —
 * cheap payload that lets crawlers/LLMs reach every member with anchor text),
 * plus a `BreadcrumbList` (`Home › ⟨Listing⟩`).
 *
 * The `ItemList` is emitted **only on the bare listing URL** (`pageUrl.search`
 * empty). Filtered/paginated variants (`?manufacturer=…`, `?page=2`)
 * canonicalize to the bare path, so publishing their partial/filtered subset
 * under that canonical `@id` would misrepresent the page; the `CollectionPage`
 * and breadcrumb (URL-only) still match the canonical and stay.
 *
 * Item `@id`s use `item.slug`: valid for every listing entity because the one
 * entity whose `public_id ≠ slug` (Location) has no listing route.
 *
 * @param totalCount the full collection size for `ItemList.numberOfItems`
 *   (the listed items are page 1); defaults to the number of items passed.
 */
export function buildListingJsonLd(
  catalogKey: CatalogEntityKey,
  items: readonly { slug: string; name: string }[],
  pageUrl: URL,
  totalCount?: number,
): Record<string, unknown> {
  const { entity_type_plural } = ENTITY_META[catalogKey];
  const { title, description } = listingMeta(catalogKey);
  const collection = pageNode('CollectionPage', pageUrl, title, description);
  const nodes: JsonLdNode[] = [collection];

  if (pageUrl.search === '') {
    const itemListId = `${pageUrl.origin + pageUrl.pathname}#items`;
    collection.mainEntity = { '@id': itemListId };
    nodes.push({
      '@type': 'ItemList',
      '@id': itemListId,
      numberOfItems: totalCount ?? items.length,
      itemListElement: items.map((item, i) => ({
        '@type': 'ListItem',
        position: i + 1,
        item: {
          '@id': absolutize(pageUrl, `/${entity_type_plural}/${item.slug}`),
          name: item.name,
        },
      })),
    });
  }

  nodes.push(breadcrumbList(pageUrl, [{ label: 'Home', href: '/' }], title));
  return jsonLdGraph(nodes);
}
