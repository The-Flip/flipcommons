/**
 * Shared SSR auth-fetch policy. Centralizes the rule that an upstream
 * `/api/auth/me/` failure must never be silently reinterpreted as a
 * user-permission outcome (#420).
 *
 * Three failure tiers; success returns the typed Me:
 *   - Network failure (openapi-fetch rejects)      → throw error(503)
 *   - Django returns non-2xx with no data          → throw error(status)
 *   - 200 with is_authenticated: false             → throw redirect('/login')
 *
 * SvelteKit's error() does NOT invoke handleError, so we log explicitly
 * before throwing to keep the failure visible in the container logs.
 */
import { error, redirect } from '@sveltejs/kit';
import { resolve } from '$app/paths';
import { getLogger } from '$lib/log';
import type { createServerClient } from './server';
import type { AuthStatusSchema } from './schema';

const log = getLogger('load-me');

type ServerClient = ReturnType<typeof createServerClient>;
type AuthenticatedMe = AuthStatusSchema & { is_authenticated: true };

export async function loadAuthenticatedMe(
  client: ServerClient,
  contextLabel: string,
): Promise<AuthenticatedMe> {
  const result = await client.GET('/api/auth/me/').catch((cause: unknown) => {
    log.error(`${contextLabel}: /me/ fetch failed`, { cause });
    return null;
  });
  if (result === null) throw error(503, 'Auth service unavailable');
  // /me/ should never return missing or malformed data in normal operation —
  // anonymous users get 200 with is_authenticated: false. Anything else
  // (5xx, 2xx with empty body, or a 200 whose body doesn't match the
  // schema) is an upstream fault, NOT a user-state verdict. Validating
  // is_authenticated explicitly is necessary because openapi-fetch does
  // not runtime-check the generated schema; a malformed `{}` body would
  // otherwise read as "anonymous" and silently redirect to /login —
  // exactly the #420-style reinterpretation we're guarding against.
  // Normalize sub-400 statuses to 500; SvelteKit's error() requires
  // 400..599 and would throw otherwise.
  if (!result.data || typeof result.data.is_authenticated !== 'boolean') {
    const status = result.response?.status;
    log.error(`${contextLabel}: /me/ returned ${status} with no/malformed data`, {
      attributes: { status: status ?? null },
    });
    throw error(status && status >= 400 ? status : 500, 'Auth service error');
  }
  if (!result.data.is_authenticated) throw redirect(302, resolve('/login'));
  return result.data as AuthenticatedMe;
}
