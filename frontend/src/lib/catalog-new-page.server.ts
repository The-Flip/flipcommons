import type { ServerLoad } from '@sveltejs/kit';
import { requireCapability } from '$lib/require-capability.server';

// Shared load for a top-level catalog entity's `new/+page.server.ts`: gate on
// `catalog.create` and seed the form name from `?name=`. Each entity's
// `new/+page.server.ts` re-exports `load` from here. Creation routes that also
// need to load a parent entity (e.g. display-subtypes, technology-subgenerations,
// nested `[slug]/.../new`) keep their own load rather than re-export this.
export const load: ServerLoad = async ({ fetch, url, request }) => {
  await requireCapability({ fetch, url, request, activity: 'catalog.create' });

  return {
    initialName: url.searchParams.get('name') ?? '',
  };
};
