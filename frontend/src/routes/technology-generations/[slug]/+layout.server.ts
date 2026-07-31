import { loadEntityPage } from '$lib/entity-page-loader.server';
import { technologyGeneration } from '$lib/entities';
import { buildEntityJsonLd } from '$lib/entities/schema-org';
import { detailCrumbs } from '$lib/route-metadata.server';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile, q } = await loadEntityPage(
    event,
    '/api/pages/technology-generation/{public_id}',
    'Technology generation',
  );
  return {
    profile,
    q,
    jsonLd: buildEntityJsonLd(
      profile,
      technologyGeneration,
      event.url,
      detailCrumbs('technology-generation'),
    ),
  };
};
