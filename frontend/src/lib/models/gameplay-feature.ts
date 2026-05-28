import type { GameplayFeatureDetailSchema } from '$lib/api/schema';
import type { ModelFrontendInfo } from './types';

export const gameplayFeature: ModelFrontendInfo<GameplayFeatureDetailSchema> = {
  entityType: 'gameplay-feature',
  schemaOrg: { types: ['DefinedTerm'] },
};
