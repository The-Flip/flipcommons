import type { LocationDetailSchema } from '$lib/api/schema';

export type LocationEditView = Pick<
  LocationDetailSchema,
  | 'name'
  | 'slug'
  | 'location_type'
  | 'description'
  | 'short_name'
  | 'code'
  | 'divisions'
  | 'aliases'
>;
