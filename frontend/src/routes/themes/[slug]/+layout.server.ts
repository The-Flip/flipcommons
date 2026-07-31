import { loadEntityPage } from '$lib/entity-page-loader.server';
import { theme } from '$lib/entities';
import { buildEntityJsonLd } from '$lib/entities/schema-org';
import { detailCrumbs } from '$lib/route-metadata.server';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile, q } = await loadEntityPage(event, '/api/pages/theme/{public_id}', 'Theme');
  // Flat trail (themes are a multi-parent DAG, so no single parent chain).
  return {
    profile,
    q,
    jsonLd: buildEntityJsonLd(profile, theme, event.url, detailCrumbs('theme')),
  };
};
