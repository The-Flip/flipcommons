import { loadEntityPage } from '$lib/entity-page-loader.server';
import { technologyGeneration } from '$lib/entities';
import { buildEntityJsonLd } from '$lib/entities/schema-org';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile } = await loadEntityPage(
    event,
    '/api/pages/technology-generation/{public_id}',
    'Technology generation',
  );
  return { profile, jsonLd: buildEntityJsonLd(profile, technologyGeneration, event.url) };
};
