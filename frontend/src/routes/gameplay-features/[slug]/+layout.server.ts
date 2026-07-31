import { loadEntityPage } from '$lib/entity-page-loader.server';
import { gameplayFeature } from '$lib/entities';
import { buildEntityJsonLd } from '$lib/entities/schema-org';
import { detailCrumbs } from '$lib/route-metadata.server';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile, q } = await loadEntityPage(
    event,
    '/api/pages/gameplay-feature/{public_id}',
    'Gameplay feature',
  );
  // Flat trail (gameplay features are a multi-parent DAG, so no single parent chain).
  return {
    profile,
    q,
    jsonLd: buildEntityJsonLd(
      profile,
      gameplayFeature,
      event.url,
      detailCrumbs('gameplay-feature'),
    ),
  };
};
