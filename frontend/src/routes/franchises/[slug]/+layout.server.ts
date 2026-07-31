import { loadEntityPage } from '$lib/entity-page-loader.server';
import { franchise } from '$lib/entities';
import { buildEntityJsonLd } from '$lib/entities/schema-org';
import { detailCrumbs } from '$lib/route-metadata.server';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile, q } = await loadEntityPage(
    event,
    '/api/pages/franchise/{public_id}',
    'Franchise',
  );
  return {
    profile,
    q,
    jsonLd: buildEntityJsonLd(profile, franchise, event.url, detailCrumbs('franchise')),
  };
};
