import { loadEntityPage } from '$lib/entity-page-loader.server';
import { franchise } from '$lib/entities';
import { buildEntityJsonLd } from '$lib/entities/schema-org';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile } = await loadEntityPage(event, '/api/pages/franchise/{public_id}', 'Franchise');
  return { profile, jsonLd: buildEntityJsonLd(profile, franchise, event.url) };
};
