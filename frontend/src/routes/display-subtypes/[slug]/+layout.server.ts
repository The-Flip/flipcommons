import { loadEntityPage } from '$lib/entity-page-loader.server';
import { displaySubtype } from '$lib/entities';
import { buildEntityJsonLd } from '$lib/entities/schema-org';
import { detailCrumbs } from '$lib/route-metadata.server';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile } = await loadEntityPage(
    event,
    '/api/pages/display-subtype/{public_id}',
    'Display subtype',
  );
  // A subtype has no listing of its own; its trail runs through the grouped
  // display-types listing and then its parent display type:
  // Home › ⟨display-types listing⟩ › ⟨parent⟩ › ⟨subtype⟩.
  const crumbs = detailCrumbs('display-type', {
    label: profile.display_type.name,
    href: `/display-types/${profile.display_type.public_id}`,
  });
  return { profile, jsonLd: buildEntityJsonLd(profile, displaySubtype, event.url, crumbs) };
};
