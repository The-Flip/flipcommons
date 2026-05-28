import { error } from '@sveltejs/kit';
import { createServerClient } from '$lib/api/server';
import type { paths } from '$lib/api/schema';

/**
 * The single-entity detail page endpoints: `/api/pages/{entity}/{public_id}`.
 * New entities pick this up automatically when codegen runs. `locations` is
 * excluded by shape — it keys off a `{location_path}` and has a root variant,
 * so it can't share this single-literal loader.
 */
type EntityPagePath = Extract<keyof paths, `/api/pages/${string}/{public_id}`>;

type EntityPageData<P extends EntityPagePath> = paths[P] extends {
  get: { responses: { 200: { content: { 'application/json': infer R } } } };
}
  ? R
  : never;

interface EntityPageLoadEvent {
  fetch: typeof fetch;
  url: URL;
  // Required: forwarded to createServerClient for cookie forwarding during SSR.
  request: Request;
  params: { slug?: string };
}

/**
 * Shared loader for an entity's `[slug]/+layout.server.ts`: builds the server
 * client, GETs the page endpoint, and maps a missing body to a 404/500. The
 * `path` literal stays at the call site so its typed response flows into
 * `profile`; the `as never` casts are localized here because openapi-fetch
 * can't resolve params/response against the generic `P`.
 */
export async function loadEntityPage<P extends EntityPagePath>(
  event: EntityPageLoadEvent,
  path: P,
  label: string,
): Promise<{ profile: EntityPageData<P> }> {
  const { fetch, url, request, params } = event;
  const client = createServerClient(fetch, url, request);
  const { data, response } = await client.GET(path, {
    params: { path: { public_id: params.slug } },
  } as never);

  if (!data) {
    if (response?.status === 404) throw error(404, `${label} not found`);
    throw error(response?.status || 500, 'Failed to load page');
  }

  return { profile: data as EntityPageData<P> };
}
