<script lang="ts">
  import DeletePage from '$lib/components/pages/record/delete/DeletePage.svelte';
  import type { BlockedState } from '$lib/components/pages/record/delete/delete-page';
  import { referrerHref, type BlockingReferrer } from '$lib/delete-flow';
  import { pluralize } from '$lib/utils';
  import { submitDelete } from './series-delete';

  let { data } = $props();
  let { preview, public_id } = $derived(data);

  let blockedReferrers = $derived(preview.blocked_by ?? []);

  let blocked = $derived<BlockedState | null>(
    blockedReferrers.length > 0
      ? {
          kind: 'referrers',
          lead: "This series can't be deleted because active titles still point at it:",
          referrers: blockedReferrers,
          renderReferrerHref: referrerHref,
          renderReferrerHint: (r: BlockingReferrer) => `references this series via ${r.relation}`,
          footer: 'Resolve these references, then try again.',
        }
      : null,
  );

  let impact = $derived({
    items: ['this series', pluralize(preview.changeset_count, 'change set')],
    note: 'You can undo this from the toast that appears on the series page, or restore the record later from its edit history.',
  });
</script>

<DeletePage
  entityLabel="Series"
  entityName={preview.name}
  {public_id}
  submit={submitDelete}
  cancelHref={`/series/${public_id}`}
  redirectAfterDelete="/series"
  editHistoryHref={`/series/${public_id}/edit-history`}
  {blocked}
  {impact}
/>
