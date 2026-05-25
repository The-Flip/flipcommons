import { isDeploymentSearchEngineIndexable } from '$lib/is-deployment-search-engine-indexable.server';
import type { RequestHandler } from './$types';

const DISALLOW_ALL = 'User-agent: *\nDisallow: /\n';

/**
 * Do NOT add user-facing routes (`/login`, `/search`, `/*\/edit`, …) here —
 * they're kept out of the index via per-page `<meta name="robots" content="noindex">`
 * (see `docs/plans/seo/NoindexMeta.md`). A `Disallow:` would block crawlers
 * from ever fetching the page, so the `noindex` meta would never be seen
 * and the URL could still appear in results via inbound links.
 */
const INDEXABLE_BODY = 'User-agent: *\nDisallow: /api/\n';

const HEADERS: HeadersInit = {
  'Content-Type': 'text/plain; charset=utf-8',
  'Cache-Control': 'public, max-age=300',
};

export const GET: RequestHandler = () => {
  const body = isDeploymentSearchEngineIndexable() ? INDEXABLE_BODY : DISALLOW_ALL;
  return new Response(body, { headers: HEADERS });
};
