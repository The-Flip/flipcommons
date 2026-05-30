import { describe, expect, it } from 'vitest';
import { buildLocationParts } from './location-links';

describe('buildLocationParts', () => {
  it('returns leaf plus ancestors using display_name', () => {
    expect(
      buildLocationParts({
        public_id: 'usa/il/chicago',
        location_type: 'city',
        display_name: 'Chicago',
        ancestors: [
          { display_name: 'Illinois', public_id: 'usa/il' },
          { display_name: 'USA', public_id: 'usa' },
        ],
      }),
    ).toEqual([
      { text: 'Chicago', href: '/locations/usa/il/chicago' },
      { text: 'Illinois', href: '/locations/usa/il' },
      { text: 'USA', href: '/locations/usa' },
    ]);
  });

  it('returns just the leaf when there are no ancestors', () => {
    expect(
      buildLocationParts({
        public_id: 'italy',
        location_type: 'country',
        display_name: 'Italy',
        ancestors: [],
      }),
    ).toEqual([{ text: 'Italy', href: '/locations/italy' }]);
  });
});
