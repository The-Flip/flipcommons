import { loadEntityPage } from '$lib/entity-page-loader.server';
import { productionStatus } from '$lib/entities';
import { buildEntityJsonLd } from '$lib/entities/schema-org';
import { detailCrumbs } from '$lib/route-metadata.server';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile } = await loadEntityPage(
    event,
    '/api/pages/production-status/{public_id}',
    'Production status',
  );
  return {
    profile,
    jsonLd: buildEntityJsonLd(
      profile,
      productionStatus,
      event.url,
      detailCrumbs('production-status'),
    ),
  };
};
