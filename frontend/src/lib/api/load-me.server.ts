/**
 * Shared SSR auth-fetch policy. Centralizes the rule that an upstream
 * `/api/auth/me/` failure must never be silently reinterpreted as a
 * user-permission outcome (#420).
 *
 * Faults are thrown as plain Errors, never via SvelteKit's error(), which
 * bypasses handleError (see handle-error.ts).
 */
import { redirect } from '@sveltejs/kit';
import { resolve } from '$app/paths';
import type { createServerClient } from './server';
import type { AuthStatusSchema } from './schema';

type ServerClient = ReturnType<typeof createServerClient>;
type AuthenticatedMe = AuthStatusSchema & { is_authenticated: true };

export async function loadAuthenticatedMe(
  client: ServerClient,
  contextLabel: string,
): Promise<AuthenticatedMe> {
  const result = await client.GET('/api/auth/me/');
  // /me/ should never return missing or malformed data in normal operation —
  // anonymous users get 200 with is_authenticated: false. Anything else
  // (5xx, 2xx with empty body, or a 200 whose body doesn't match the
  // schema) is an upstream fault, NOT a user-state verdict. Validating
  // is_authenticated explicitly is necessary because openapi-fetch does
  // not runtime-check the generated schema; a malformed `{}` body would
  // otherwise read as "anonymous" and silently redirect to /login —
  // exactly the #420-style reinterpretation we're guarding against.
  if (!result.data || typeof result.data.is_authenticated !== 'boolean') {
    throw new Error(
      `${contextLabel}: /me/ returned ${result.response?.status} with no/malformed data`,
    );
  }
  if (!result.data.is_authenticated) throw redirect(302, resolve('/login'));
  return result.data as AuthenticatedMe;
}
