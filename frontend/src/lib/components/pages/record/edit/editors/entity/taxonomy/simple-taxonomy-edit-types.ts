import type { RichTextSchema } from '$lib/api/schema';

/**
 * Structural superset of every per-entity page payload that simple-taxonomy
 * editors operate on. `display_order` is optional because not every payload
 * carries it; consumers without it omit the display-order section so the
 * field is never read at runtime.
 */
export type SimpleTaxonomyEditView = {
  name: string;
  slug: string;
  description: RichTextSchema;
  display_order?: number | null;
};
