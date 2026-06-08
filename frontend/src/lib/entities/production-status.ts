import type { EntityRef, TaxonomySchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

/**
 * The one ProductionStatus value with code-level meaning: a "produced" machine
 * shows no status row on its detail page. Compared best-effort only — if the
 * row is renamed or absent the match simply fails and "produced" becomes
 * visible (cosmetic, recoverable). Twin of the backend `PRODUCED_SLUG` in
 * `backend/apps/catalog/models/taxonomy.py`; a rename must update both.
 *
 * Note `EntityRef` carries `public_id` (the slug) on the wire, not `.slug`.
 */
export const PRODUCED_SLUG = 'produced';

/**
 * Whether a Model's own production status should be displayed: present and not
 * "produced". Shared by `ModelSpecsSidebar` (the render) and the model detail
 * section-visibility flags so they can't drift into rendering an empty section.
 *
 * The multi-model Title rollup does NOT use this — its `produced`/null
 * suppression happens in the backend (`AgreedSpecsSchema`).
 */
export function showsProductionStatus(ps: EntityRef | null | undefined): boolean {
  return !!ps && ps.public_id !== PRODUCED_SLUG;
}

export const productionStatus: EntityInfo<TaxonomySchema> = {
  entityType: 'production-status',
  listing: {
    description:
      'Status in regards to commercial production, such as whether it has been commercially produced, announced, or is a one-off never intended to be produced.',
  },
  schemaOrg: { types: ['DefinedTerm'] },
};
