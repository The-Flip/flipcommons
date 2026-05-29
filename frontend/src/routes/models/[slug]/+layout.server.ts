import { loadEntityPage } from '$lib/entity-page-loader.server';
import { model } from '$lib/entities';
import { buildEntityJsonLd } from '$lib/entities/schema-org';
import type { Crumb } from '$lib/components/jsonld';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile } = await loadEntityPage(event, '/api/pages/model/{public_id}', 'Machine');

  // Breadcrumb: Home › Title › Model.
  // There's no Titles (plural): the /titles listing is CSR (excluded).
  // There's no Models (plural): there's no /models listing, only titles.
  const crumbs: Crumb[] = [{ label: 'Home', href: '/' }];
  if (profile.title) {
    crumbs.push({ label: profile.title.name, href: `/titles/${profile.title.public_id}` });
  }

  return { profile, jsonLd: buildEntityJsonLd(profile, model, event.url, crumbs) };
};
