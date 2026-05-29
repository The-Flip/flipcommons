import type { ModelDetailSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const model: EntityInfo<ModelDetailSchema> = {
  entityType: 'model',
  schemaOrg: {
    types: ['Game', 'ProductModel'],
    fieldMap: {
      year: { property: 'releaseDate', transform: 'year' },
      hero_image_url: 'image',
    },
    // Start minimal: the many other FKs (system, technology_generation,
    // display_type, cabinet, …) have no clean schema.org property and are left
    // for a follow-up. The denormalized manufacturer/franchise/series fields
    // aren't `_meta` relationships and are transitively discoverable, so they
    // are deliberately not mapped.
    relationshipMap: { corporate_entity: 'brand', title: 'exampleOfWork', themes: 'genre' },
  },
};
