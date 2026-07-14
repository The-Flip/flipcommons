/**
 * Test fixtures for catalog detail-page wire shapes. Use these instead of
 * hand-writing the ~45-field `satisfies *DetailSchema` literals in tests, so
 * that adding a field to the backend schema is a one-line edit here rather
 * than an N-file sweep. Mirrors the `error-fixtures.ts` pattern.
 */

import type { ModelDetailSchema, TitleDetailSchema } from './schema';

/**
 * Build a complete {@link ModelDetailSchema} for tests, overriding only the
 * fields a given test cares about.
 */
export function makeModelDetail(overrides: Partial<ModelDetailSchema> = {}): ModelDetailSchema {
  return {
    name: 'Medieval Madness',
    public_id: 'medieval-madness',
    last_modified: '2026-01-01T00:00:00Z',
    slug: 'medieval-madness',
    year: null,
    month: null,
    manufacturer: null,
    corporate_entity: null,
    title: { name: 'Medieval Madness', public_id: 'medieval-madness' },
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
    bootleg_of: null,
    bootlegs: [],
    licensed_build_of: null,
    licensed_builds: [],
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
    relationships: [],
    uploaded_media: [],
    ...overrides,
  };
}

/**
 * Build a complete {@link TitleDetailSchema} for tests, overriding only the
 * fields a given test cares about. For the nested `model_detail`, pass
 * {@link makeModelDetail}.
 */
export function makeTitleDetail(overrides: Partial<TitleDetailSchema> = {}): TitleDetailSchema {
  return {
    name: 'Medieval Madness',
    public_id: 'medieval-madness',
    last_modified: '2026-01-01T00:00:00Z',
    slug: 'medieval-madness',
    description: { text: '', html: '', plain: '', citations: [], attribution: null },
    abbreviations: [],
    hero_image_url: null,
    franchise: null,
    series: null,
    machines: [],
    credits: [],
    agreed_specs: { themes: [], gameplay_features: [], reward_types: [], tags: [] },
    related_titles: [],
    media: [],
    opdb_id: null,
    fandom_page_id: null,
    model_detail: null,
    ...overrides,
  };
}
