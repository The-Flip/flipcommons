/**
 * Shared mock data for link-type autocomplete DOM tests.
 *
 * Vitest's vi.mock factories are hoisted above imports, so they can't
 * reference normal imports. Test files use an async factory with a dynamic
 * import to pull these fixtures into the mock:
 *
 *   import { LINK_TYPES, SEARCH_RESULTS } from './link-types-fixtures';
 *
 *   vi.mock('$lib/api/link-types', async () => {
 *     const f = await import('./link-types-fixtures');
 *     return {
 *       fetchLinkTypes: vi.fn().mockResolvedValue(f.LINK_TYPES),
 *       searchLinkTargets: vi.fn().mockResolvedValue({ results: f.SEARCH_RESULTS }),
 *     };
 *   });
 */
import type { LinkType, LinkTarget } from '$lib/api/link-types';

export const LINK_TYPES: LinkType[] = [
  { name: 'title', label: 'Title', description: 'Link to a title', flow: 'standard' },
  {
    name: 'manufacturer',
    label: 'Manufacturer',
    description: 'Link to a manufacturer',
    flow: 'standard',
  },
  { name: 'cite', label: 'Citation', description: 'Cite a source', flow: 'custom' },
];

export const SEARCH_RESULTS: LinkTarget[] = [
  { ref: 'attack-from-mars', label: 'Attack from Mars' },
  { ref: 'medieval-madness', label: 'Medieval Madness' },
];
