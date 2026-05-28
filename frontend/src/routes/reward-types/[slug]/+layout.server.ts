import { loadEntityPage } from '$lib/entity-page-loader.server';
import { rewardType } from '$lib/models';
import { buildEntityJsonLd } from '$lib/models/schema-org';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile } = await loadEntityPage(
    event,
    '/api/pages/reward-type/{public_id}',
    'Reward type',
  );
  return { profile, jsonLd: buildEntityJsonLd(profile, rewardType, event.url) };
};
