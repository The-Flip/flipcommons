import { render } from 'svelte/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { pageState } = vi.hoisted(() => ({
  pageState: {
    params: { slug: 'medieval-madness' },
    url: new URL('http://localhost:5173/models/medieval-madness'),
  },
}));

vi.mock('$app/state', () => ({
  page: pageState,
}));

import Harness from './layout.test-harness.svelte';
import type { ModelDetailSchema } from '$lib/api/schema';

const MOCK_MODEL = {
  name: 'Medieval Madness',
  slug: 'medieval-madness',
  year: 1997,
  month: null,
  manufacturer: { name: 'Williams', public_id: 'williams' },
  corporate_entity: {
    name: 'Williams Electronics',
    public_id: 'williams-electronics',
  },
  title: { name: 'Medieval Madness', public_id: 'medieval-madness' },
  description: { text: '', html: '', plain: '', citations: [], attribution: null },
  technology_generation: null,
  technology_subgeneration: null,
  display_type: null,
  display_subtype: null,
  system: null,
  cabinet: null,
  game_format: null,
  player_count: null,
  flipper_count: null,
  production_quantity: '',
  thumbnail_url: null,
  hero_image_url: null,
  image_attribution: null,
  ipdb_id: null,
  opdb_id: null,
  pinside_id: null,
  ipdb_rating: null,
  pinside_rating: null,
  variant_of: null,
  variants: [],
  variant_siblings: [],
  variant_features: [],
  converted_from: null,
  conversions: [],
  remake_of: null,
  remakes: [],
  themes: [],
  tags: [],
  gameplay_features: [],
  reward_types: [],
  abbreviations: [],
  extra_data: {},
  franchise: null,
  series: null,
  title_models: [],
  credits: [],
  uploaded_media: [],
} satisfies ModelDetailSchema;

describe('model layout', () => {
  beforeEach(() => {
    pageState.params.slug = 'medieval-madness';
    pageState.url = new URL('http://localhost:5173/models/medieval-madness');
  });

  it('omits the Back link on the detail route', () => {
    const { body } = render(Harness, {
      props: { data: { model: MOCK_MODEL } },
    });

    expect(body).toContain('History');
    expect(body).not.toContain('>Back<');
  });

  it('renders a Back link on media subroutes', () => {
    pageState.url = new URL('http://localhost:5173/models/medieval-madness/media');

    const { body } = render(Harness, {
      props: { data: { model: MOCK_MODEL } },
    });

    expect(body).toContain('>Back<');
    expect(body).toContain('/models/medieval-madness');
  });
});
