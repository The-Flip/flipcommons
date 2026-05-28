import { describe, it, expect } from 'vitest';
import { CATALOG_META, type CatalogEntityKey } from './models/model-meta';
import { catalogRoutesByEntity } from './route-metadata.server';

// The route-metadata walker classifies /{plural}/[public-id]/edit (and
// /new, /delete) by URL pattern, not by reading auth gates. This test is
// the other half: for every catalog page route classified by the walker,
// assert the conventional gate exists — either inline in the route file or
// delegated to an approved shared gate helper — with the expected activity.
//
// The test is driven by classified page routes — not by an inventory of
// existing server files — so deleting a +page.server.ts (leaving its
// +page.svelte to render ungated) fails the test directly.
//
// A route satisfies the convention two ways:
//   1. inline — imports $lib/require-capability.server and names the activity
//   2. delegated — re-exports/imports an approved shared gate helper (below),
//      each of which is itself gate-checked in the final describe block.
// Either way the safety property holds: every classified route is gated with
// the right activity, transitively. (The /delete family has always used the
// delegated form via the shared delete-preview loader.)

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

// Raw source of the shared $lib gate helpers, so the final describe block can
// assert the helpers a route delegates to actually carry the gate.
const HELPER_SOURCES = import.meta.glob('/src/lib/catalog-*.server.ts', {
  eager: true,
  query: '?raw',
  import: 'default',
}) as Record<string, string>;

// Approved shared gate helpers a route may delegate to instead of gating
// inline. `entry`, when set, is the function a route calls to delegate (the
// parent-scoped creation helper is consumed by calling it, not re-exporting);
// helpers without `entry` are consumed by re-exporting their `load`.
interface GateHelper {
  module: string;
  entry?: string;
}
const EDIT_GATE_HELPERS: readonly GateHelper[] = [{ module: '$lib/catalog-edit-layout.server' }];
const NEW_GATE_HELPERS: readonly GateHelper[] = [
  { module: '$lib/catalog-new-page.server' },
  { module: '$lib/catalog-new-with-parent-page.server', entry: 'loadCreateWithParent' },
];

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function importsRequireCapability(src: string): boolean {
  return /from\s+['"]\$lib\/require-capability\.server['"]/.test(src);
}

function usesActivity(src: string, activity: string): boolean {
  return new RegExp(`activity:\\s*['"]${activity.replace('.', '\\.')}['"]`).test(src);
}

// True only if the route actually delegates to the helper — re-exports its
// `load`, or imports and calls its `entry`. A bare import that doesn't drive
// the route's load is NOT delegation (the route could still export its own
// ungated load), so it must not satisfy the convention.
function delegatesTo(src: string, helper: GateHelper): boolean {
  const mod = escapeRegExp(helper.module);
  // Re-export form: `export { ssr, load } from '<module>'`.
  if (new RegExp(`export\\s*\\{[^}]*\\bload\\b[^}]*\\}\\s*from\\s+['"]${mod}['"]`).test(src)) {
    return true;
  }
  // Call form: import the entry from <module> and invoke it.
  if (helper.entry && new RegExp(`from\\s+['"]${mod}['"]`).test(src)) {
    return new RegExp(`\\b${escapeRegExp(helper.entry)}\\s*\\(`).test(src);
  }
  return false;
}

// A route is gated for `activity` if it gates inline or delegates to one of
// the approved shared helpers.
function isGated(src: string, activity: string, helpers: readonly GateHelper[]): boolean {
  const inline = importsRequireCapability(src) && usesActivity(src, activity);
  const delegated = helpers.some((helper) => delegatesTo(src, helper));
  return inline || delegated;
}

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
          expect(
            isGated(src, 'catalog.edit', EDIT_GATE_HELPERS),
            `${path} must gate catalog.edit — inline via $lib/require-capability.server or by delegating to ${EDIT_GATE_HELPERS.map((h) => h.module).join(' / ')}`,
          ).toBe(true);
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
          expect(
            isGated(src, 'catalog.create', NEW_GATE_HELPERS),
            `${path} must gate catalog.create — inline via $lib/require-capability.server or by delegating to ${NEW_GATE_HELPERS.map((h) => h.module).join(' / ')}`,
          ).toBe(true);
        }
      });
    });
  }
});

// The delegated form is only safe if the shared helpers actually carry the
// gate. Verify each approved helper imports require-capability and names the
// activity it claims to enforce — otherwise a route could "delegate" to an
// ungated helper and silently pass above.
describe('shared catalog gate helpers carry their gate', () => {
  function helperSrc(file: string): string {
    const path = `/src/lib/${file}`;
    const src = HELPER_SOURCES[path];
    expect(src, `${path} is missing — approved gate helper not found`).toBeDefined();
    return src;
  }

  it.each([
    ['catalog-edit-layout.server.ts', 'catalog.edit'],
    ['catalog-new-page.server.ts', 'catalog.create'],
    ['catalog-new-with-parent-page.server.ts', 'catalog.create'],
  ])('%s imports require-capability and gates %s', (file, activity) => {
    const src = helperSrc(file);
    expect(
      importsRequireCapability(src),
      `${file} must import $lib/require-capability.server`,
    ).toBe(true);
    expect(usesActivity(src, activity), `${file} must use activity ${activity}`).toBe(true);
  });
});
