<script lang="ts">
  import DeletePage from '$lib/components/DeletePage.svelte';
  import type { BlockedState, ParentBreadcrumb } from '$lib/components/delete-page';
  import type { BlockingReferrer } from '$lib/delete-flow';
  import { pluralize } from '$lib/utils';
  import { submitDelete } from './display-subtype-delete';

  let { data } = $props();
  let { preview, public_id } = $derived(data);

  let blockedReferrers = $derived(preview.blocked_by ?? []);

  let parentBreadcrumb = $derived<ParentBreadcrumb | undefined>(
    preview.parent
      ? {
          text: preview.parent.name,
          href: `/display-types/${preview.parent.public_id}`,
        }
      : undefined,
  );

  let blocked = $derived<BlockedState | null>(
    blockedReferrers.length > 0
      ? {
          kind: 'referrers',
          lead: "This subtype can't be deleted because active records still point at it:",
          referrers: blockedReferrers,
          renderReferrerHref: () => null,
          renderReferrerHint: (r: BlockingReferrer) => `references this subtype via ${r.relation}`,
          footer: 'Resolve these references, then try again.',
        }
      : null,
  );

  let impact = $derived({
    items: ['this subtype', pluralize(preview.changeset_count, 'change set')],
    note: 'You can undo this from the toast that appears on the display types page, or restore the record later from its edit history.',
  });
</script>

<DeletePage
  entityLabel="Subtype"
  entityName={preview.name}
  {public_id}
  submit={submitDelete}
  cancelHref={`/display-subtypes/${public_id}`}
  redirectAfterDelete="/display-types"
  editHistoryHref={`/display-subtypes/${public_id}/edit-history`}
  {parentBreadcrumb}
  {blocked}
  {impact}
/>
