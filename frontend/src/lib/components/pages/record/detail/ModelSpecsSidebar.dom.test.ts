import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import type { EntityRef, ModelDetailSchema } from '$lib/api/schema';
import ModelSpecsSidebar from './ModelSpecsSidebar.svelte';

/** Minimal model with no feature-section content; tests override one field. */
const BASE_MODEL = {
  name: 'Cancelled Project',
  public_id: 'cancelled-project',
  last_modified: '2026-01-01T00:00:00Z',
  slug: 'cancelled-project',
  year: null,
  month: null,
  manufacturer: null,
  corporate_entity: null,
  title: { name: 'Cancelled Project', public_id: 'cancelled-project' },
  description: { text: '', html: '', plain: '', citations: [], attribution: null },
  technology_generation: null,
  technology_subgeneration: null,
  display_type: null,
  display_subtype: null,
  system: null,
  cabinet: null,
  game_format: null,
  production_status: null,
  player_count: null,
  flipper_count: null,
  production_quantity: '',
  thumbnail_url: null,
  hero_image_url: null,
  image_attribution: null,
  ipdb_id: null,
  opdb_id: null,
  pinside_id: null,
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

function renderWith(production_status: EntityRef | null) {
  render(ModelSpecsSidebar, { props: { model: { ...BASE_MODEL, production_status } } });
}

describe('ModelSpecsSidebar production status', () => {
  it('shows a non-produced status as a link to its page', () => {
    renderWith({ name: 'Unreleased', public_id: 'unreleased' });

    expect(screen.getByText('Production status')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Unreleased' })).toHaveAttribute(
      'href',
      '/production-statuses/unreleased',
    );
  });

  it('hides the produced status', () => {
    renderWith({ name: 'Produced', public_id: 'produced' });

    expect(screen.queryByText('Production status')).toBeNull();
  });

  it('hides a null status', () => {
    renderWith(null);

    expect(screen.queryByText('Production status')).toBeNull();
  });
});
