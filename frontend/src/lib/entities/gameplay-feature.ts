import type { GameplayFeatureDetailSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const gameplayFeature: EntityInfo<GameplayFeatureDetailSchema> = {
  entityType: 'gameplay-feature',
  schemaOrg: { types: ['DefinedTerm'] },
};
