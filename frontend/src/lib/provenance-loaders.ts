/**
 * Shared loaders for per-entity provenance subroutes.
 *
 * Both edit-history and sources subroutes are identical across entities
 * except for a single entity-type string, so each loader is a one-liner
 * per route.
 */
import { error } from '@sveltejs/kit';
import { createServerClient } from '$lib/api/server';
import type { CatalogEntityKey } from '$lib/models/model-meta';

type LoadEvent = {
  fetch: typeof fetch;
  url: URL;
  request: Request;
};

export async function loadEditHistory(
  event: LoadEvent,
  entityType: CatalogEntityKey,
  public_id: string,
) {
  const client = createServerClient(event.fetch, event.url, event.request);
  const { data, response } = await client.GET(
    '/api/pages/edit-history/{entity_type}/{public_id}/',
    {
      params: { path: { entity_type: entityType, public_id } },
    },
  );

  if (!data) {
    throw error(response.status || 500, 'Failed to load edit history');
  }

  return { changesets: data };
}

export async function loadSources(
  event: LoadEvent,
  entityType: CatalogEntityKey,
  public_id: string,
) {
  const client = createServerClient(event.fetch, event.url, event.request);
  const { data, response } = await client.GET('/api/pages/sources/{entity_type}/{public_id}/', {
    params: { path: { entity_type: entityType, public_id } },
  });

  if (!data) {
    throw error(response.status || 500, 'Failed to load sources');
  }

  return {
    sources: data.sources,
    evidence: data.evidence,
  };
}
