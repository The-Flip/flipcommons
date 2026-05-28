import type { RichTextSchema } from '$lib/api/schema';
import { CATALOG_META } from '$lib/models/model-meta';
import { jsonLdGraph, breadcrumbList, absolutize, type JsonLdNode } from '$lib/components/jsonld';
import type { ModelFrontendInfo } from './types';

/**
 * The minimal entity facts every schema.org node needs. Widens in a later
 * tranche (images, external IDs, the `public_id` body-layer migration).
 */
export interface EntityBaseFacts {
  name: string;
  slug: string;
  description?: RichTextSchema | null;
}

/**
 * Build the schema.org node for a single catalog entity: `@type`, a canonical
 * `@id`, `name`, and an untruncated `description` (the backend's flattened
 * `description.plain`). The `@id` is the entity's canonical URL
 * (`/{entity_type_plural}/{slug}`), independent of the current path — so it's
 * stable even when the layout load runs on a sub-route.
 */
export function buildSchemaOrgNode<T extends EntityBaseFacts>(
  entity: T,
  info: ModelFrontendInfo<T>,
  pageUrl: URL,
): JsonLdNode {
  const typeSpec = info.schemaOrg.types;
  const types = typeof typeSpec === 'function' ? typeSpec(entity) : typeSpec;
  const meta = CATALOG_META[info.entityType];
  const node: JsonLdNode = {
    '@type': types.length === 1 ? types[0] : [...types],
    '@id': absolutize(pageUrl, `/${meta.entity_type_plural}/${entity.slug}`),
    name: entity.name,
  };
  const desc = entity.description?.plain?.trim() ?? '';
  if (desc) node.description = desc;
  return node;
}

/**
 * Build the full `@graph` for an entity detail page: the entity node plus a
 * `Home › {name}` breadcrumb. The listing page is omitted from the trail
 * because it's CSR/non-crawlable.
 */
export function buildEntityJsonLd<T extends EntityBaseFacts>(
  entity: T,
  info: ModelFrontendInfo<T>,
  pageUrl: URL,
): Record<string, unknown> {
  return jsonLdGraph([
    buildSchemaOrgNode(entity, info, pageUrl),
    breadcrumbList(pageUrl, [{ label: 'Home', href: '/' }], entity.name),
  ]);
}
