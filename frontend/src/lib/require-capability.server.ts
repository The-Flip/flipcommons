import { redirect } from '@sveltejs/kit';
import { resolve } from '$app/paths';
import { createServerClient } from '$lib/api/server';
import { loadAuthenticatedMe } from '$lib/api/load-me.server';
import type { Activity } from '$lib/api/schema';

interface RequireCapabilityOptions {
  fetch: typeof fetch;
  url: URL;
  // Required: forwarded to createServerClient so the user's Cookie
  // header reaches Django. SvelteKit's event.fetch only forwards
  // cookies same-origin, and SSR crosses to a loopback origin in prod.
  // Dropping this would re-introduce #420 (gate sees anonymous /me/).
  request: Request;
  activity: Activity;
}

// Redirect anonymous users to `/login` and authenticated-but-uncapable
// users to `/verify-email` before they fill out a form they cannot submit.
// The SPA auth gate is UX-only — the backend remains the source of truth.
export async function requireCapability({
  fetch,
  url,
  request,
  activity,
}: RequireCapabilityOptions): Promise<void> {
  const client = createServerClient(fetch, url, request);
  const me = await loadAuthenticatedMe(client, 'requireCapability');
  if (me.capabilities?.[activity] !== true) {
    throw redirect(302, resolve('/verify-email'));
  }
}
