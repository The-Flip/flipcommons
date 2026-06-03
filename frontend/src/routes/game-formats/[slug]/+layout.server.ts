import { loadEntityPage } from '$lib/entity-page-loader.server';
import { gameFormat } from '$lib/entities';
import { buildEntityJsonLd } from '$lib/entities/schema-org';
import { detailCrumbs } from '$lib/route-metadata.server';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile } = await loadEntityPage(
    event,
    '/api/pages/game-format/{public_id}',
    'Game format',
  );
  return {
    profile,
    jsonLd: buildEntityJsonLd(profile, gameFormat, event.url, detailCrumbs('game-format')),
  };
};
