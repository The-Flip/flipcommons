import type { CorporateEntityDetailSchema } from '$lib/api/schema';

/**
 * Canonical corporate-entity page payload for SSR route tests. Typed with
 * `satisfies` so a new backend field is a compile-time error here rather than a
 * silent gap in every test that mocks the page endpoint. Tests spread-and-override
 * for their variations (e.g. `{ ...MOCK_CORPORATE_ENTITY, titles: [] }`).
 */
export const MOCK_CORPORATE_ENTITY = {
  name: 'Williams Electronics',
  public_id: 'williams-electronics',
  last_modified: '2026-01-01T00:00:00Z',
  slug: 'williams-electronics',
  description: { text: '', plain: '', html: '', citations: [], attribution: null },
  manufacturer: { name: 'Williams', public_id: 'williams' },
  year_of_first_model: 1985,
  year_of_last_model: 1999,
  operating_status: 'unknown',
  aliases: [],
  titles: [
    {
      name: 'Medieval Madness',
      public_id: 'medieval-madness',
      year: 1997,
      manufacturer_name: 'Williams',
      thumbnail_url: null,
    },
  ],
  locations: [],
} satisfies CorporateEntityDetailSchema;
