import type { ServerLoad } from '@sveltejs/kit';
import { requireCapability } from '$lib/require-capability.server';

// Shared auth gate for every catalog entity's `[slug]/edit/*` subtree.
// Each entity's `edit/+layout.server.ts` re-exports `ssr` + `load` from here
// so the gate stays defined once. Routes with a different activity (e.g.
// kiosk.edit) must keep their own layout rather than re-export this.
export const ssr = false;

export const load: ServerLoad = async ({ fetch, url, request }) => {
  await requireCapability({ fetch, url, request, activity: 'catalog.edit' });
};
