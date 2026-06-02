import type { TechnologySubgenerationDetailSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const technologySubgeneration: EntityInfo<TechnologySubgenerationDetailSchema> = {
  entityType: 'technology-subgeneration',
  schemaOrg: { types: ['DefinedTerm'] },
};
