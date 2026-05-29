import { loadEntityPage } from '$lib/entity-page-loader.server';
import { creditRole } from '$lib/entities';
import { buildEntityJsonLd } from '$lib/entities/schema-org';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile } = await loadEntityPage(
    event,
    '/api/pages/credit-role/{public_id}',
    'Credit role',
  );
  return { profile, jsonLd: buildEntityJsonLd(profile, creditRole, event.url) };
};
