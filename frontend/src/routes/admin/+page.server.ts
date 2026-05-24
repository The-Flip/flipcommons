import { redirect } from '@sveltejs/kit';
import { resolve } from '$app/paths';
import type { PageServerLoad } from './$types';

// `/admin` will host other admin pages over time. While the dashboard
// is the only one, hitting `/admin` itself routes there. When a second
// admin page lands, replace this redirect with a real index page.
export const load: PageServerLoad = () => {
  throw redirect(303, resolve('/admin/dashboard'));
};
