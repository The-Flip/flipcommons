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
import { makeModelDetail } from '$lib/api/detail-fixtures';

const MOCK_MODEL = makeModelDetail({
  year: 1997,
  manufacturer: { name: 'Williams', public_id: 'williams' },
  corporate_entity: { name: 'Williams Electronics', public_id: 'williams-electronics' },
});

describe('model layout', () => {
  beforeEach(() => {
    pageState.params.slug = 'medieval-madness';
    pageState.url = new URL('http://localhost:5173/models/medieval-madness');
  });

  it('omits the Back link on the detail route', () => {
    const { body } = render(Harness, {
      props: { data: { profile: MOCK_MODEL } },
    });

    expect(body).toContain('History');
    expect(body).not.toContain('>Back<');
  });

  it('renders a Back link on media subroutes', () => {
    pageState.url = new URL('http://localhost:5173/models/medieval-madness/media');

    const { body } = render(Harness, {
      props: { data: { profile: MOCK_MODEL } },
    });

    expect(body).toContain('>Back<');
    expect(body).toContain('/models/medieval-madness');
  });
});
