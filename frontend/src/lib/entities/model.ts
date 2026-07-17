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
  externalRefs: {
    ipdb_id: {
      label: 'Internet Pinball Database',
      urlTemplate: 'https://www.ipdb.org/machine.cgi?id={id}',
      showId: true,
    },
    // OPDB's public URLs key off an internal autoincrement we don't store; our
    // opdb_id is the alphanumeric cross-DB id. Emit as identifier until we
    // ingest the resolvable form.
    opdb_id: { identifier: 'OPDB' },
    pinside_id: { label: 'Pinside', urlTemplate: 'https://pinside.com/pinball/machine/{id}' },
  },
};
