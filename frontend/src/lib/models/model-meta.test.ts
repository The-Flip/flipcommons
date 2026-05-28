import { describe, it, expect } from 'vitest';
import { catalogRoutesByEntity } from '../route-metadata.server';
import { CATALOG_META, type CatalogEntityKey } from './model-meta';

// Every linkable entity must have detail + edit-history + sources routes.
// edit-history/ and sources/ are thin wrappers over $lib/provenance-loaders
// and $lib/components, but each entity still needs its own +page.server.ts +
// +page.svelte so the files live under the entity's shared +layout.server.ts
// — otherwise navigating to edit-history re-runs the entity load. The cost
// of forgetting is an invisible UX gap (see credit-role, missing for an
// unknown period). This test catches it.
//
// Classification trust: route-metadata.test.ts already enforces that every
// page-bearing route classifies into exactly one bucket. So if a catalog
// route directory exists, it MUST classify as one of the catalog-* kinds —
// no risk of a route slipping past as 'unclassified' here.

// The +page.server.ts files for edit-history and sources do the actual data
// loading (loadEditHistory / loadSources from $lib/provenance-loaders). If
// the server file is deleted, the route still classifies — the +page.svelte
// is what classification looks at — but the page would render with missing
// `data.evidence` / `data.sources` and crash at runtime.
const PAGE_SERVER_SOURCES = import.meta.glob('/src/routes/**/+page.server.ts', {
  eager: true,
  query: '?raw',
  import: 'default',
}) as Record<string, string>;

const detailRoutes = catalogRoutesByEntity((cls) => cls.kind === 'catalog-detail');
const editHistoryRoutes = catalogRoutesByEntity((cls) => cls.kind === 'catalog-edit-history');
const sourcesRoutes = catalogRoutesByEntity((cls) => cls.kind === 'catalog-sources');

describe('model-meta vs route tree', () => {
  it.each(Object.keys(CATALOG_META) as CatalogEntityKey[])(
    '%s has a catalog-detail route',
    (key) => {
      expect(
        detailRoutes.has(key),
        `CATALOG_META contains "${key}" but no route classifies as catalog-detail for it. ` +
          `Either add the /${CATALOG_META[key].entity_type_plural}/[slug] (or [...path]) route, ` +
          `or remove the entity from CATALOG_META.`,
      ).toBe(true);
    },
  );

  it.each(Object.keys(CATALOG_META) as CatalogEntityKey[])(
    '%s has a catalog-edit-history route with a +page.server.ts loader',
    (key) => {
      const ids = editHistoryRoutes.get(key) ?? [];
      expect(ids, `No catalog-edit-history route for ${key}`).not.toHaveLength(0);
      for (const id of ids) {
        const path = `/src/routes${id}/+page.server.ts`;
        expect(
          PAGE_SERVER_SOURCES[path],
          `${path} is missing — the /edit-history page exists but its loader doesn't, so data.evidence will be undefined at runtime.`,
        ).toBeDefined();
      }
    },
  );

  it.each(Object.keys(CATALOG_META) as CatalogEntityKey[])(
    '%s has a catalog-sources route with a +page.server.ts loader',
    (key) => {
      const ids = sourcesRoutes.get(key) ?? [];
      expect(ids, `No catalog-sources route for ${key}`).not.toHaveLength(0);
      for (const id of ids) {
        const path = `/src/routes${id}/+page.server.ts`;
        expect(
          PAGE_SERVER_SOURCES[path],
          `${path} is missing — the /sources page exists but its loader doesn't, so data.sources will be undefined at runtime.`,
        ).toBeDefined();
      }
    },
  );
});
