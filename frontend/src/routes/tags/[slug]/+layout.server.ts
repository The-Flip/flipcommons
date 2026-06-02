import { loadEntityPage } from '$lib/entity-page-loader.server';
import { tag } from '$lib/entities';
import { buildEntityJsonLd } from '$lib/entities/schema-org';
import { detailCrumbs } from '$lib/route-metadata.server';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile } = await loadEntityPage(event, '/api/pages/tag/{public_id}', 'Tag');
  return { profile, jsonLd: buildEntityJsonLd(profile, tag, event.url, detailCrumbs('tag')) };
};
