import { describe, it, expect } from 'vitest';
import { CATALOG_META, type CatalogEntityKey } from './api/catalog-meta';
import { catalogRoutesByEntity } from './route-metadata.server';

// The route-metadata walker classifies /{plural}/[public-id]/edit (and
// /new, /delete) by URL pattern, not by reading auth gates. This test is
// the other half: for every catalog page route classified by the walker,
// assert the conventional gate file exists at the expected path and
// imports the expected helper.
//
// The test is driven by classified page routes — not by an inventory of
// existing server files — so deleting a +page.server.ts (leaving its
// +page.svelte to render ungated) fails the test directly.

const SERVER_SOURCES = {
  ...(import.meta.glob('/src/routes/**/+layout.server.ts', {
    eager: true,
    query: '?raw',
    import: 'default',
  }) as Record<string, string>),
  ...(import.meta.glob('/src/routes/**/+page.server.ts', {
    eager: true,
    query: '?raw',
    import: 'default',
  }) as Record<string, string>),
};

// Build per-entity registries of page routes by kind. catalog-edit is
// restricted to /edit (the layout's own page); /edit/[section] also
// classifies as catalog-edit but inherits the same +layout.server.ts gate
// and shouldn't be re-checked.
const newRoutesByEntity = catalogRoutesByEntity((cls) => cls.kind === 'catalog-new');
const deleteRoutesByEntity = catalogRoutesByEntity((cls) => cls.kind === 'catalog-delete');
const editRoutesByEntity = catalogRoutesByEntity(
  (cls, id) => cls.kind === 'catalog-edit' && id.endsWith('/edit'),
);

describe('catalog auth-gate convention', () => {
  for (const key of Object.keys(CATALOG_META) as CatalogEntityKey[]) {
    describe(key, () => {
      it('every /edit route has a +layout.server.ts gated with catalog.edit', () => {
        const ids = editRoutesByEntity.get(key) ?? [];
        expect(ids, `No catalog-edit page route classified for ${key}`).not.toHaveLength(0);
        for (const id of ids) {
          const path = `/src/routes${id}/+layout.server.ts`;
          const src = SERVER_SOURCES[path];
          expect(
            src,
            `${path} is missing — the /edit page exists but its layout server gate doesn't`,
          ).toBeDefined();
          expect(src, `${path} must import $lib/require-capability.server`).toMatch(
            /from\s+['"]\$lib\/require-capability\.server['"]/,
          );
          expect(src, `${path} must use activity catalog.edit`).toMatch(
            /activity:\s*['"]catalog\.edit['"]/,
          );
        }
      });

      it('every /delete route has a +page.server.ts using the shared delete-preview loader', () => {
        const ids = deleteRoutesByEntity.get(key) ?? [];
        expect(ids, `No catalog-delete page route classified for ${key}`).not.toHaveLength(0);
        for (const id of ids) {
          const path = `/src/routes${id}/+page.server.ts`;
          const src = SERVER_SOURCES[path];
          expect(
            src,
            `${path} is missing — the /delete page exists but its server gate doesn't`,
          ).toBeDefined();
          expect(src, `${path} must import $lib/delete-preview-loader.server`).toMatch(
            /from\s+['"]\$lib\/delete-preview-loader\.server['"]/,
          );
        }
      });

      it('every /new route has a +page.server.ts gated with catalog.create', () => {
        const ids = newRoutesByEntity.get(key) ?? [];
        expect(ids, `No catalog-new page route classified for ${key}`).not.toHaveLength(0);
        for (const id of ids) {
          const path = `/src/routes${id}/+page.server.ts`;
          const src = SERVER_SOURCES[path];
          expect(
            src,
            `${path} is missing — the /new page exists but its server gate doesn't`,
          ).toBeDefined();
          expect(src, `${path} must import $lib/require-capability.server`).toMatch(
            /from\s+['"]\$lib\/require-capability\.server['"]/,
          );
          expect(src, `${path} must use activity catalog.create`).toMatch(
            /activity:\s*['"]catalog\.create['"]/,
          );
        }
      });
    });
  }
});
