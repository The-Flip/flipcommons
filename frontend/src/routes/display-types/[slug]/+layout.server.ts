import { loadEntityPage } from '$lib/entity-page-loader.server';
import { displayType } from '$lib/models';
import { buildEntityJsonLd } from '$lib/models/schema-org';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile } = await loadEntityPage(
    event,
    '/api/pages/display-type/{public_id}',
    'Display type',
  );
  return { profile, jsonLd: buildEntityJsonLd(profile, displayType, event.url) };
};
