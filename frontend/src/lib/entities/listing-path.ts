/**
 * The URL path of a catalog entity's listing page. Client-safe (imported by
 * listing components for filter navigation) as well as by the server-side
 * route metadata and sitemap.
 */

import type { RouteId } from '$app/types';
import { ENTITY_META, type CatalogEntityKey } from '$lib/entities/entity-meta';

/**
 * Listing routes that do NOT live at `/{entity_type_plural}`. Everything that
 * derives a listing URL — route classification, `listingCrumb`, the sitemap's
 * listing-`lastmod` keying, the listing shell's filter navigation — consults
 * `listingPath()`, so an entry here moves the listing everywhere at once.
 * Detail routes are unaffected: they classify by the entity's plural segment
 * regardless of where the listing lives.
 */
export const LISTING_ROUTE_OVERRIDES = {
  // The heterogeneous games listing: Title and Model cards under the roll-up,
  // keyed under `title` because Titles are its unit of account (the page
  // passes `catalogKey="title"`, and `listingMeta('title')` carries the
  // "Games" copy). `/titles` itself is a 301 to `/games`.
  title: '/games',
} as const satisfies Partial<Record<CatalogEntityKey, RouteId>>;

/**
 * The URL path of an entity's listing page: its declared override, else the
 * model-driven default `/{entity_type_plural}`.
 */
export function listingPath(entity: CatalogEntityKey): string {
  const overrides: Partial<Record<CatalogEntityKey, RouteId>> = LISTING_ROUTE_OVERRIDES;
  return overrides[entity] ?? `/${ENTITY_META[entity].entity_type_plural}`;
}
