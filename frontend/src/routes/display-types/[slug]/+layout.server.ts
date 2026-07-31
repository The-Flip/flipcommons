import { loadEntityPage } from '$lib/entity-page-loader.server';
import { displayType } from '$lib/entities';
import { buildEntityJsonLd } from '$lib/entities/schema-org';
import { detailCrumbs } from '$lib/route-metadata.server';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile, q } = await loadEntityPage(
    event,
    '/api/pages/display-type/{public_id}',
    'Display type',
  );
  return {
    profile,
    q,
    jsonLd: buildEntityJsonLd(profile, displayType, event.url, detailCrumbs('display-type')),
  };
};
