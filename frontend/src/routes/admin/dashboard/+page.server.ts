import { error } from '@sveltejs/kit';
import { createServerClient } from '$lib/api/server';
import { ADMIN_DASHBOARD_DEPEND_KEY } from './_dependencies';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ fetch, url, request, depends }) => {
  // Lets the page call `invalidate(ADMIN_DASHBOARD_DEPEND_KEY)` to refetch
  // without re-running the parent layout's auth gate.
  depends(ADMIN_DASHBOARD_DEPEND_KEY);

  const client = createServerClient(fetch, url, request);
  const { data, response } = await client.GET('/api/pages/admin/dashboard/');

  if (!data) {
    throw error(response.status || 500, 'Failed to load admin dashboard');
  }

  return { stats: data };
};
