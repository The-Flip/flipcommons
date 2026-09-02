/** Which site shell a route gets: focus, minimal or the full site chrome. */

import type { RouteId } from '$app/types';
import { matchDetailSubroute } from './detail-subroute-match';

/**
 * Focus-mode routes render their own minimal chrome (no site Nav/Footer or
 * page-content wrapper). Patterns, in route-ID form:
 *   /:entity/new                            create a top-level record
 *   /:entity/[slug]/:child/new              create a nested record
 *   /:entity/[slug]/edit                    edit (no section)
 *   /:entity/[slug]/edit/[section]          edit a section
 *   /:entity/[slug]/delete                  destructive confirmation
 *   /:entity/[slug]/edit-history            audit: changeset history
 *   /:entity/[slug]/sources                 audit: source claims
 *   /kiosk                                  museum kiosk visitor grid
 *
 * `edit`, `delete`, `edit-history` and `sources` are read through
 * `matchDetailSubroute`, so they only count when they follow a record's
 * public-id segment. A record whose slug is `sources` is served by
 * `/titles/[slug]` and still gets full chrome.
 *
 * `new` needs no such guard: SvelteKit's route priority gives `/:entity/new`
 * to the create page, not the detail page.
 */
const FOCUS_SUBROUTES_NESTED = new Set(['edit']);
const FOCUS_SUBROUTES_TERMINAL = new Set(['delete', 'edit-history', 'sources']);
const FOCUS_EXACT_ROUTES: ReadonlySet<RouteId> = new Set<RouteId>(['/kiosk']);

const MINIMAL_SHELL_EXACT_ROUTES: ReadonlySet<RouteId> = new Set<RouteId>([
  '/signup',
  '/auth/error',
]);

/**
 * Minimal-shell routes render the brand header (site name only, no nav) and
 * the site footer, but skip the primary nav and account menu. Used for
 * single-task flows where the user is mid-commit (e.g. signup) and reaching
 * for the nav would lose their pending state.
 */
export function isMinimalShellRoute(routeId: RouteId | null): boolean {
  return routeId !== null && MINIMAL_SHELL_EXACT_ROUTES.has(routeId);
}

export function isFocusModeRoute(routeId: RouteId | null): boolean {
  if (routeId === null) return false;
  if (FOCUS_EXACT_ROUTES.has(routeId)) return true;

  const segments = routeId.split('/').filter(Boolean);
  if (segments.length === 0) return false;

  if (segments[segments.length - 1] === 'new') return true;

  const subroute = matchDetailSubroute(routeId);
  if (!subroute) return false;

  if (FOCUS_SUBROUTES_NESTED.has(subroute)) return true;
  if (FOCUS_SUBROUTES_TERMINAL.has(subroute) && segments.length === 3) return true;

  return false;
}
