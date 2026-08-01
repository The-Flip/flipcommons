/**
 * Test fixtures for catalog detail-page wire shapes. Use these instead of
 * hand-writing the ~45-field `satisfies *DetailSchema` literals in tests, so
 * that adding a field to the backend schema is a one-line edit here rather
 * than an N-file sweep. Mirrors the `error-fixtures.ts` pattern.
 */

import type { GameListSchema, ModelDetailSchema, TitleDetailSchema } from './schema';

/**
 * A games-list pin with no dimension set — the `pin` an unfiltered list
 * response carries (list-typed dimensions are always present on the wire).
 */
export function emptyPin(): GameListSchema['pin'] {
  return {
    theme: [],
    gameplay_feature: [],
    reward_type: [],
    edge: [],
    cabinet: [],
    game_format: [],
    production_status: [],
  };
}

/**
 * Build a complete {@link GameListSchema} — the games embed a detail-page
 * payload carries — overriding only the fields a given test cares about.
 */
export function makeGamesList(overrides: Partial<GameListSchema> = {}): GameListSchema {
  return { items: [], count: 0, pin: emptyPin(), ...overrides };
}

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
    remake_of: null,
    remakes: [],
    export_edition_of: null,
    export_editions: [],
    export_markets: [],
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
    inbound_relationships: [],
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
    models: [],
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
