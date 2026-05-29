import { loadEntityPage } from '$lib/entity-page-loader.server';
import { manufacturer } from '$lib/entities';
import { buildEntityJsonLd } from '$lib/entities/schema-org';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile } = await loadEntityPage(
    event,
    '/api/pages/manufacturer/{public_id}',
    'Manufacturer',
  );
  return { profile, jsonLd: buildEntityJsonLd(profile, manufacturer, event.url) };
};
