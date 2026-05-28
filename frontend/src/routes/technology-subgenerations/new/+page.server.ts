import { redirect } from '@sveltejs/kit';
import { resolve } from '$app/paths';
import { loadCreateWithParent } from '$lib/catalog-new-with-parent-page.server';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = ({ fetch, url, request }) =>
  loadCreateWithParent({
    fetch,
    url,
    request,
    fetchParents: (client) => client.GET('/api/technology-generations/'),
    onMissingParent: () => redirect(302, resolve('/technology-generations')),
    errorLabel: 'Failed to load technology generations.',
  });
