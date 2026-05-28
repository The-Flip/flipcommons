import { loadEntityPage } from '$lib/entity-page-loader.server';
import { technologySubgeneration } from '$lib/models';
import { buildEntityJsonLd } from '$lib/models/schema-org';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile } = await loadEntityPage(
    event,
    '/api/pages/technology-subgeneration/{public_id}',
    'Technology subgeneration',
  );
  return { profile, jsonLd: buildEntityJsonLd(profile, technologySubgeneration, event.url) };
};
