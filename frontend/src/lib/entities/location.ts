import type { LocationDetailSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

/**
 * schema.org type per `location_type`. `location_type` is `str | None`, so
 * both `null` and `''` fall through to the `AdministrativeArea` fallback —
 * don't special-case `''` to a different type than `null`.
 */
function locationTypes(loc: LocationDetailSchema): readonly string[] {
  switch (loc.location_type) {
    case 'country':
      return ['Country'];
    case 'state':
      return ['State'];
    case 'city':
      return ['City'];
    default:
      return ['AdministrativeArea'];
  }
}

export const location: EntityInfo<LocationDetailSchema> = {
  entityType: 'location',
  schemaOrg: {
    types: locationTypes,
    fieldMap: { short_name: 'alternateName' },
  },
};
