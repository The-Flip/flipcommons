/** Which sub-route of a record's detail page a route is showing. */

import type { RouteId } from '$app/types';
import { matchDetailSubroute } from './detail-subroute-match';

export type DetailSubrouteMode = 'detail' | 'edit' | 'media' | 'sources' | 'edit-history';

export function resolveDetailSubrouteMode(routeId: RouteId | null): DetailSubrouteMode {
  const subroute = matchDetailSubroute(routeId);
  switch (subroute) {
    case 'edit-history':
      return 'edit-history';
    case 'sources':
      return 'sources';
    case 'media':
      return 'media';
    case 'edit':
      return 'edit';
    default:
      return 'detail';
  }
}
