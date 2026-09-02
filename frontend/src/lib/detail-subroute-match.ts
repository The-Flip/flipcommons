/** Reading a record's sub-route out of a SvelteKit route ID. */

import type { RouteId } from '$app/types';
import { isPublicIdSegment } from './route-shape';

/**
 * Returns the sub-route segment of a record route — the `sources` in
 * `/titles/[slug]/sources` — or `null` when the route isn't one.
 *
 * Matching runs on the route ID rather than the URL, which is what makes the
 * two hard cases fall out for free. A record's public id is always exactly one
 * route segment however many URL segments it spans, so a Location's
 * `/locations/[...path]/sources` reads the same as a Title's
 * `/titles/[slug]/sources`. And a record whose slug happens to be `sources`
 * is served by `/titles/[slug]`, which has no sub-route segment at all.
 *
 * Both `isFocusModeRoute` and `resolveDetailSubrouteMode` use this helper so
 * they cannot drift on those rules.
 */
export function matchDetailSubroute(routeId: RouteId | null): string | null {
  if (routeId === null) return null;
  const segments = routeId.split('/').filter(Boolean);
  if (segments.length < 3) return null;
  if (!isPublicIdSegment(segments[1])) return null;
  return segments[2];
}
