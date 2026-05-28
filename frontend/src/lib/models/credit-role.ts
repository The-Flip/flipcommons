import type { CreditRoleDetailSchema } from '$lib/api/schema';
import type { ModelFrontendInfo } from './types';

export const creditRole: ModelFrontendInfo<CreditRoleDetailSchema> = {
  entityType: 'credit-role',
  schemaOrg: { types: ['Occupation'] },
};
