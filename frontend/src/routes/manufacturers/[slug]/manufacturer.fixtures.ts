import type { ManufacturerDetailPageSchema } from '$lib/api/schema';

/**
 * Canonical manufacturer page payload for SSR route tests. Typed with
 * `satisfies` so a new backend field is a compile-time error here rather than a
 * silent gap in every test that mocks the page endpoint. Tests spread-and-override
 * for their variations (e.g. `{ ...MOCK_MANUFACTURER, games: { items: [], count: 0 } }`).
 */
export const MOCK_MANUFACTURER = {
  name: 'Williams',
  public_id: 'williams',
  last_modified: '2026-01-01T00:00:00Z',
  slug: 'williams',
  description: {
    text: 'Historic manufacturer [1].',
    plain: 'Historic manufacturer.',
    html: '<p>Historic manufacturer.</p>',
    citations: [
      {
        id: 10,
        index: 1,
        source_name: 'Pinball Sourcebook',
        source_type: 'book',
        author: 'Jane Example',
        year: 1999,
        locator: 'p. 42',
        quote: '',
        links: [],
      },
      {
        id: 11,
        index: 1,
        source_name: 'Pinball Sourcebook',
        source_type: 'book',
        author: 'Jane Example',
        year: 1999,
        locator: 'p. 42',
        quote: '',
        links: [],
      },
    ],
    attribution: null,
  },
  year_of_first_model: 1985,
  year_of_last_model: 1999,
  operating_status: 'unknown',
  logo_url: null,
  website: 'https://williams.example',
  entities: [
    {
      name: 'Williams Electronics',
      public_id: 'williams-electronics',
      year_of_first_model: 1985,
      year_of_last_model: 1999,
      operating_status: 'unknown',
      locations: [],
    },
  ],
  games: {
    items: [
      {
        entity_type: 'title' as const,
        name: 'Medieval Madness',
        public_id: 'medieval-madness',
        year: 1997,
        manufacturer: { name: 'Williams', public_id: 'williams' },
        thumbnail_url: null,
      },
    ],
    count: 1,
  },
  systems: [{ name: 'WPC-95', public_id: 'wpc-95' }],
  persons: [{ name: 'Pat Lawlor', public_id: 'pat-lawlor', roles: ['Designer'] }],
  uploaded_media: [
    {
      asset_uuid: 'asset-1',
      category: 'cabinet',
      is_primary: true,
      renditions: {
        thumb: 'https://example.com/thumb.jpg',
        display: 'https://example.com/display.jpg',
      },
    },
  ],
} satisfies ManufacturerDetailPageSchema;
