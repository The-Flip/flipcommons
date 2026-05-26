import { env } from '$env/dynamic/private';
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
const INDEXABLE_BODY_PREFIX = 'User-agent: *\nDisallow: /api/\n';

const HEADERS: HeadersInit = {
  'Content-Type': 'text/plain; charset=utf-8',
  'Cache-Control': 'public, max-age=300',
};

export const GET: RequestHandler = ({ url }) => {
  if (!isDeploymentSearchEngineIndexable()) {
    return new Response(DISALLOW_ALL, { headers: HEADERS });
  }
  // SITE_ORIGIN at runtime, mirroring the dev fallback pattern in
  // `frontend/src/lib/api/server.ts`. Railway builds enforce SITE_ORIGIN
  // at build time (svelte.config.js); the fallback only matters in
  // `make dev` where the env var may be unset.
  const origin = env.SITE_ORIGIN?.trim() || url.origin;
  const body = `${INDEXABLE_BODY_PREFIX}Sitemap: ${origin}/sitemap.xml\n`;
  return new Response(body, { headers: HEADERS });
};
