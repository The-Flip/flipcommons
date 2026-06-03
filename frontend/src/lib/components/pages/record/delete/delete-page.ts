/**
 * Public type contracts for `DeletePage.svelte`. Lives in a sibling .ts
 * module because Svelte components cannot re-export types from their
 * `<script>` tag.
 */
import type { BlockingReferrer } from '$lib/delete-flow';

export type ParentBreadcrumb = { text: string; href: string };

export type BlockedState =
  | { kind: 'message'; lead: string }
  | {
      kind: 'referrers';
      lead: string;
      referrers: BlockingReferrer[];
      renderReferrerHref?: (r: BlockingReferrer) => string | null;
      renderReferrerHint: (r: BlockingReferrer) => string;
      footer?: string;
    };

export type ImpactState = {
  items: string[];
  note: string;
};
