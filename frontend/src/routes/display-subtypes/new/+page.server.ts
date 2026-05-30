import { redirect } from '@sveltejs/kit';
import { resolve } from '$app/paths';
import { loadCreateWithParent } from '$lib/catalog-new-with-parent-page.server';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = ({ fetch, url, request }) =>
  loadCreateWithParent({
    fetch,
    url,
    request,
    fetchParents: (client) => client.GET('/api/display-types/'),
    onMissingParent: () => redirect(302, resolve('/display-types')),
    errorLabel: 'Failed to load display types.',
  });
