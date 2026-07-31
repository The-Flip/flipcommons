/**
 * Permanent redirect from the old `/titles` listing URL to `/games`,
 * query string intact so shared filter links keep working. Only the bare
 * segment redirects — `/titles/<slug>` and `/titles/new` are real routes.
 */

import { redirect } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = ({ url }) => {
  redirect(301, `/games${url.search}`);
};
