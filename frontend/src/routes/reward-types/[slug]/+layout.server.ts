import { loadEntityPage } from '$lib/entity-page-loader.server';
import { rewardType } from '$lib/entities';
import { buildEntityJsonLd } from '$lib/entities/schema-org';
import { detailCrumbs } from '$lib/route-metadata.server';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile, q } = await loadEntityPage(
    event,
    '/api/pages/reward-type/{public_id}',
    'Reward type',
  );
  return {
    profile,
    q,
    jsonLd: buildEntityJsonLd(profile, rewardType, event.url, detailCrumbs('reward-type')),
  };
};
