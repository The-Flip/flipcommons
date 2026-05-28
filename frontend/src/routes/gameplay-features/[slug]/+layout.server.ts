import { loadEntityPage } from '$lib/entity-page-loader.server';
import { gameplayFeature } from '$lib/models';
import { buildEntityJsonLd } from '$lib/models/schema-org';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile } = await loadEntityPage(
    event,
    '/api/pages/gameplay-feature/{public_id}',
    'Gameplay feature',
  );
  return { profile, jsonLd: buildEntityJsonLd(profile, gameplayFeature, event.url) };
};
