import { loadEntityPage } from '$lib/entity-page-loader.server';
import { technologySubgeneration } from '$lib/entities';
import { buildEntityJsonLd } from '$lib/entities/schema-org';
import { detailCrumbs } from '$lib/route-metadata.server';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile, q } = await loadEntityPage(
    event,
    '/api/pages/technology-subgeneration/{public_id}',
    'Technology subgeneration',
  );
  // A subgeneration has no listing of its own; its trail runs through the
  // grouped technology-generations listing and then its parent generation:
  // Home › ⟨technology-generations listing⟩ › ⟨parent⟩ › ⟨subgeneration⟩.
  const crumbs = detailCrumbs('technology-generation', {
    label: profile.technology_generation.name,
    href: `/technology-generations/${profile.technology_generation.public_id}`,
  });
  return {
    profile,
    q,
    jsonLd: buildEntityJsonLd(profile, technologySubgeneration, event.url, crumbs),
  };
};
