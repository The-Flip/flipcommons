import type { CorporateEntityDetailSchema } from '$lib/api/schema';

export type CorporateEntityEditView = Pick<
  CorporateEntityDetailSchema,
  'name' | 'slug' | 'description' | 'aliases'
>;
