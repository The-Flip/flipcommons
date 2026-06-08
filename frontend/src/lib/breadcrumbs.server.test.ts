import { describe, expect, it, vi } from 'vitest';
import type { CatalogEntityKey } from '$lib/entities/entity-meta';

import { load as cabinet } from '../routes/cabinets/[slug]/+layout.server';
import { load as corporateEntity } from '../routes/corporate-entities/[slug]/+layout.server';
import { load as creditRole } from '../routes/credit-roles/[slug]/+layout.server';
import { load as displaySubtype } from '../routes/display-subtypes/[slug]/+layout.server';
import { load as displayType } from '../routes/display-types/[slug]/+layout.server';
import { load as franchise } from '../routes/franchises/[slug]/+layout.server';
import { load as gameFormat } from '../routes/game-formats/[slug]/+layout.server';
import { load as gameplayFeature } from '../routes/gameplay-features/[slug]/+layout.server';
import { load as location } from '../routes/locations/[...path]/+layout.server';
import { load as manufacturer } from '../routes/manufacturers/[slug]/+layout.server';
import { load as model } from '../routes/models/[slug]/+layout.server';
import { load as person } from '../routes/people/[slug]/+layout.server';
import { load as productionStatus } from '../routes/production-statuses/[slug]/+layout.server';
import { load as rewardType } from '../routes/reward-types/[slug]/+layout.server';
import { load as series } from '../routes/series/[slug]/+layout.server';
import { load as system } from '../routes/systems/[slug]/+layout.server';
import { load as tag } from '../routes/tags/[slug]/+layout.server';
import { load as technologyGeneration } from '../routes/technology-generations/[slug]/+layout.server';
import { load as technologySubgeneration } from '../routes/technology-subgenerations/[slug]/+layout.server';
import { load as theme } from '../routes/themes/[slug]/+layout.server';
import { load as title } from '../routes/titles/[slug]/+layout.server';

/**
 * One central spec for every catalog detail page's JSON-LD `BreadcrumbList`,
 * so the trails can be read — and judged — in relation to one another.
 *
 * `CRUMBS` is the whole spec: entity → the breadcrumb name chain. The listing
 * crumb is the entity's resolved `listing.breadcrumb` (which defaults to
 * `heading` → `title` → `label_plural` — e.g. "Pinball Machine Display Types",
 * or the terser "Notable People" override for people); the last entry is the
 * page itself. The `satisfies Record<CatalogEntityKey, …>` makes a new catalog
 * entity fail to compile until its breadcrumb is declared here — the guard that
 * the missing `series` crumb would have tripped.
 *
 * The test stays faithful by driving each entity's real `+layout.server.ts`
 * `load` (via a `fetch` that returns the entity profile, exactly as the
 * per-route JSON-LD tests do) and reading the emitted `BreadcrumbList`. So the
 * scannable table below is also an executable assertion about what ships.
 */
const CRUMBS = {
  title: ['Home', 'Pinball Machines', 'Godzilla'],
  model: ['Home', 'Pinball Machines', 'Godzilla', 'Godzilla Pro'],
  manufacturer: ['Home', 'Pinball Manufacturers', 'Stern'],
  'corporate-entity': ['Home', 'Pinball Manufacturers', 'Stern', 'Stern, Inc.'],
  person: ['Home', 'Notable People', 'Pat Lawlor'],
  series: ['Home', 'Series', 'Eight Ball'],
  franchise: ['Home', 'Franchises', 'Star Wars'],
  system: ['Home', 'Systems', 'SPIKE 2'],
  location: ['Home', 'United States', 'Illinois', 'Chicago'],
  cabinet: ['Home', 'Cabinets', 'Cocktail'],
  theme: ['Home', 'Pinball Machine Themes', 'Fantasy'],
  'gameplay-feature': ['Home', 'Pinball Machine Gameplay Features', 'Multiball'],
  'game-format': ['Home', 'Game Formats', 'Pinball'],
  'production-status': ['Home', 'Production Statuses', 'Unreleased'],
  'reward-type': ['Home', 'Reward Types', 'Replay'],
  'credit-role': ['Home', 'Credit Roles', 'Designer'],
  tag: ['Home', 'Tags', 'Prototype'],
  'display-type': ['Home', 'Pinball Machine Display Types', 'Dot Matrix'],
  'display-subtype': ['Home', 'Pinball Machine Display Types', 'Dot Matrix', 'Nixie Tube'],
  'technology-generation': ['Home', 'Pinball Technology Generations', 'Solid State'],
  'technology-subgeneration': ['Home', 'Pinball Technology Generations', 'Solid State', 'PC-Based'],
} satisfies Record<CatalogEntityKey, string[]>;

/**
 * The few entities whose trail comes from a related entity, not just their own
 * name. The values are the related refs the layout reads; their names must
 * echo the middle crumbs in `CRUMBS` (a wrong parent ref then fails the chain).
 * Every other entity needs only `name` (the listing crumb is model-derived).
 */
const PARENTS: Partial<Record<CatalogEntityKey, Record<string, unknown>>> = {
  model: { title: { name: 'Godzilla', public_id: 'godzilla' } },
  'corporate-entity': { manufacturer: { name: 'Stern', public_id: 'stern' } },
  location: {
    location_type: 'city',
    ancestors: [
      { name: 'United States', public_id: 'usa' },
      { name: 'Illinois', public_id: 'usa/il' },
    ],
  },
  title: { machines: [], model_detail: null },
  'display-subtype': { display_type: { name: 'Dot Matrix', public_id: 'dot-matrix' } },
  'technology-subgeneration': {
    technology_generation: { name: 'Solid State', public_id: 'solid-state' },
  },
};

// SvelteKit types each `load` as returning `void | Partial<PageData>`, so the
// driver casts the awaited result to read `jsonLd` — same as the per-route
// JSON-LD tests. `never` params let every concrete load satisfy one signature.
type Load = (event: never) => unknown;

const LOADS = {
  title,
  model,
  manufacturer,
  'corporate-entity': corporateEntity,
  person,
  series,
  franchise,
  system,
  location,
  cabinet,
  theme,
  'gameplay-feature': gameplayFeature,
  'game-format': gameFormat,
  'production-status': productionStatus,
  'reward-type': rewardType,
  'credit-role': creditRole,
  tag,
  'display-type': displayType,
  'display-subtype': displaySubtype,
  'technology-generation': technologyGeneration,
  'technology-subgeneration': technologySubgeneration,
} satisfies Record<CatalogEntityKey, Load>;

/** A minimal entity profile carrying only what the breadcrumb assembler reads. */
function profileFor(entity: CatalogEntityKey): unknown {
  const crumbs = CRUMBS[entity];
  const name = crumbs[crumbs.length - 1] ?? '';
  return {
    name,
    public_id: 'x',
    last_modified: '',
    description: { text: '', html: '', plain: '', citations: [] },
    ...(PARENTS[entity] ?? {}),
  };
}

/** An event whose `fetch` returns the given profile, so the real loader runs. */
function eventFor(entity: CatalogEntityKey, profile: unknown): unknown {
  const fetch = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(profile), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
  return {
    fetch,
    url: new URL('https://flipcommons.org/x'),
    request: new Request('https://flipcommons.org/x'),
    // Location is the one rest-param route; the rest take a `[slug]`.
    params: entity === 'location' ? { path: 'usa/il/chicago' } : { slug: 'x' },
  };
}

function breadcrumbNames(jsonLd: Record<string, unknown> | undefined): string[] {
  const graph = (jsonLd?.['@graph'] ?? []) as Record<string, unknown>[];
  const crumb = graph.find((n) => n['@type'] === 'BreadcrumbList');
  const items = (crumb?.itemListElement ?? []) as Record<string, unknown>[];
  return items.map((i) => i.name as string);
}

describe('catalog detail breadcrumbs', () => {
  for (const key of Object.keys(CRUMBS) as CatalogEntityKey[]) {
    const expected = CRUMBS[key];
    it(`${key}: ${expected.join(' › ')}`, async () => {
      const event = eventFor(key, profileFor(key));
      const result = (await LOADS[key](event as never)) as { jsonLd?: Record<string, unknown> };
      expect(breadcrumbNames(result.jsonLd)).toEqual(expected);
    });
  }
});
