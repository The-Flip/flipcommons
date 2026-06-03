import type { SeriesDetailSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const series: EntityInfo<SeriesDetailSchema> = {
  entityType: 'series',
  listing: { description: 'Pinball titles sharing an original, non-licensed lineage.' },
  schemaOrg: { types: ['CreativeWorkSeries'] },
};
