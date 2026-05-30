import { loadEntityPage } from '$lib/entity-page-loader.server';
import { series } from '$lib/entities';
import { buildEntityJsonLd } from '$lib/entities/schema-org';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile } = await loadEntityPage(event, '/api/pages/series/{public_id}', 'Series');
  return { profile, jsonLd: buildEntityJsonLd(profile, series, event.url) };
};
