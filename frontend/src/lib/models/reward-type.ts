import type { RewardTypeDetailSchema } from '$lib/api/schema';
import type { ModelFrontendInfo } from './types';

export const rewardType: ModelFrontendInfo<RewardTypeDetailSchema> = {
  entityType: 'reward-type',
  schemaOrg: { types: ['DefinedTerm'] },
};
