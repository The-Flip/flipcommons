/**
 * Every `/edit-history` and `/sources` route renders a component that reads the
 * entity context, and `getEntityContext()` throws when no ancestor layout
 * published it — a hard 500 on every one of that entity's sub-route URLs.
 *
 * The per-entity page tests can't catch that: each one renders through a
 * `*.test-harness.svelte` that calls `setEntityContext` itself, so a layout that
 * forgets it still passes them. This walks the real layout chain instead.
 */

import { describe, it, expect } from 'vitest';
import type { RouteId } from '$app/types';
import { catalogRoutesByEntity } from './route-metadata.server';

const LAYOUT_SOURCES = import.meta.glob('/src/routes/**/+layout.svelte', {
  eager: true,
  query: '?raw',
  import: 'default',
}) as Record<string, string>;

// Layouts delegate to shared shells (`SimpleTaxonomyDetailLayout` →
// `TaxonomyDetailBaseLayout`), so the call can be several components deep.
const COMPONENT_SOURCES = import.meta.glob('/src/lib/**/*.svelte', {
  eager: true,
  query: '?raw',
  import: 'default',
}) as Record<string, string>;

/** Resolves a Svelte import specifier to its `import.meta.glob` key, or null if it isn't one of ours. */
function resolveComponent(specifier: string, importerPath: string): string | null {
  if (!specifier.endsWith('.svelte')) return null;
  if (specifier.startsWith('$lib/')) return `/src/lib/${specifier.slice('$lib/'.length)}`;
  if (!specifier.startsWith('.')) return null;
  const dir = importerPath.slice(0, importerPath.lastIndexOf('/'));
  const segments = `${dir}/${specifier}`.split('/');
  const out: string[] = [];
  for (const segment of segments) {
    if (segment === '.' || segment === '') continue;
    if (segment === '..') out.pop();
    else out.push(segment);
  }
  return `/${out.join('/')}`;
}

/** True if this component or anything it transitively renders calls `setEntityContext`. */
function publishesEntityContext(path: string, source: string, seen = new Set<string>()): boolean {
  if (seen.has(path)) return false;
  seen.add(path);
  if (source.includes('setEntityContext(')) return true;
  for (const [, specifier] of source.matchAll(/from\s+['"]([^'"]+\.svelte)['"]/g)) {
    const resolved = resolveComponent(specifier, path);
    if (resolved === null) continue;
    const nested = COMPONENT_SOURCES[resolved];
    if (nested !== undefined && publishesEntityContext(resolved, nested, seen)) return true;
  }
  return false;
}

/** The `+layout.svelte` files that wrap a route, leaf-first. */
function layoutChain(id: RouteId): { path: string; source: string }[] {
  const segments = id.slice(1).split('/');
  const chain: { path: string; source: string }[] = [];
  for (let i = segments.length; i >= 0; i--) {
    const path = `/src/routes${i === 0 ? '' : `/${segments.slice(0, i).join('/')}`}/+layout.svelte`;
    const source = LAYOUT_SOURCES[path];
    if (source !== undefined) chain.push({ path, source });
  }
  return chain;
}

const CONTEXT_DEPENDENT_ROUTES: RouteId[] = [
  ...catalogRoutesByEntity(
    (cls) => cls.kind === 'catalog-edit-history' || cls.kind === 'catalog-sources',
  ).values(),
].flat();

describe('entity context is published to every sub-route that reads it', () => {
  it('finds sub-routes to check', () => {
    // Guards against the classification channel changing shape and silently
    // reducing the sweep below to nothing.
    expect(CONTEXT_DEPENDENT_ROUTES.length).toBeGreaterThan(20);
  });

  it.each(CONTEXT_DEPENDENT_ROUTES)('%s', (id) => {
    const chain = layoutChain(id);
    const publisher = chain.find(({ path, source }) => publishesEntityContext(path, source));
    expect(
      publisher?.path ?? null,
      `No layout wrapping ${id} calls setEntityContext, so getEntityContext() will throw ` +
        `and every URL under this route will 500. Add the call to the entity's ` +
        `+layout.svelte (see titles/[slug]/+layout.svelte), or render it through ` +
        `TaxonomyDetailBaseLayout, which publishes the context for you.`,
    ).not.toBeNull();
  });
});
