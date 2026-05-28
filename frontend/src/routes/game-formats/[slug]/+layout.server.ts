import { loadEntityPage } from '$lib/entity-page-loader.server';
import { gameFormat } from '$lib/models';
import { buildEntityJsonLd } from '$lib/models/schema-org';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile } = await loadEntityPage(
    event,
    '/api/pages/game-format/{public_id}',
    'Game format',
  );
  return { profile, jsonLd: buildEntityJsonLd(profile, gameFormat, event.url) };
};
