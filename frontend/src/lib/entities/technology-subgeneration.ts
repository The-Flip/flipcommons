import type { TechnologySubgenerationDetailPageSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const technologySubgeneration: EntityInfo<TechnologySubgenerationDetailPageSchema> = {
  entityType: 'technology-subgeneration',
  schemaOrg: { types: ['DefinedTerm'] },
};
