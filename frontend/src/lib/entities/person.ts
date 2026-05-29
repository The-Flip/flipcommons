import type { PersonDetailSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const person: EntityInfo<PersonDetailSchema> = {
  entityType: 'person',
  schemaOrg: {
    types: ['Person'],
    // Year-only birth/death dates; month/day components are deliberately
    // omitted for v1 (keeps Person on the generic 1:1 path).
    fieldMap: {
      birth_year: { property: 'birthDate', transform: 'year' },
      death_year: { property: 'deathDate', transform: 'year' },
      photo_url: 'image',
    },
  },
};
