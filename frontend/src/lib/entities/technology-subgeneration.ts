import type { TechnologySubgenerationPageSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const technologySubgeneration: EntityInfo<TechnologySubgenerationPageSchema> = {
  entityType: 'technology-subgeneration',
  schemaOrg: { types: ['DefinedTerm'] },
};
