import { loadEntityPage } from '$lib/entity-page-loader.server';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = (event) =>
  loadEntityPage(event, '/api/pages/model/{public_id}', 'Machine');
