import { requireCapability } from '$lib/require-capability.server';
import type { LayoutServerLoad } from './$types';

// Single auth gate for the whole admin SPA area. Any page that lands
// under `/admin/*` inherits this gate; do not re-implement per-page.
export const load: LayoutServerLoad = async ({ fetch, url, request }) => {
  await requireCapability({ fetch, url, request, activity: 'admin_area.view' });
};
