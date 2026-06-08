import type { PageServerLoad } from './$types';
import { loadSources } from '$lib/provenance-loaders';

export const load: PageServerLoad = (event) =>
  loadSources(event, 'production-status', event.params.slug);
