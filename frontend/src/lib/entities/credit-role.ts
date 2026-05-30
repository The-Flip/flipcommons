import type { CreditRoleDetailSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const creditRole: EntityInfo<CreditRoleDetailSchema> = {
  entityType: 'credit-role',
  schemaOrg: { types: ['Occupation'] },
};
