import { loadEntityPage } from '$lib/entity-page-loader.server';
import { requireCapability } from '$lib/require-capability.server';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  await requireCapability({ ...event, activity: 'catalog.create' });

  // Fetch the parent manufacturer directly — this page escapes the parent
  // layout via `+page@.svelte`, so parent-layout data is not inherited.
  const { profile } = await loadEntityPage(
    event,
    '/api/pages/manufacturer/{public_id}',
    'Manufacturer',
  );

  return {
    manufacturer: { name: profile.name, slug: profile.slug },
    initialName: event.url.searchParams.get('name') ?? '',
  };
};
