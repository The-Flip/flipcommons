import { loadEntityPage } from '$lib/entity-page-loader.server';
import { requireCapability } from '$lib/require-capability.server';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  await requireCapability({ ...event, activity: 'catalog.create' });

  // Fetch the parent title so the heading renders the real name ("Pokémon"
  // rather than the ASCII slug "pokemon"). We fetch directly here rather than
  // inheriting from the parent `[slug]/+layout.server.ts` because this page
  // escapes the parent layout via `+page@.svelte` — SvelteKit does not inherit
  // parent-layout data through a layout reset.
  const { profile } = await loadEntityPage(event, '/api/pages/title/{public_id}', 'Title');

  return { title: { name: profile.name, slug: profile.slug } };
};
