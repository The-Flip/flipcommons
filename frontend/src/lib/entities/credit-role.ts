import type { CreditRoleDetailSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const creditRole: EntityInfo<CreditRoleDetailSchema> = {
  entityType: 'credit-role',
  listing: { description: 'Roles credited in game development.' },
  schemaOrg: { types: ['Occupation'] },
};
