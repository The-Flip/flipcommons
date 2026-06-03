<script lang="ts">
  import DeletePage from '$lib/components/pages/record/delete/DeletePage.svelte';
  import type { BlockedState } from '$lib/components/pages/record/delete/delete-page';
  import type { BlockingReferrer } from '$lib/delete-flow';
  import { pluralize } from '$lib/utils';
  import { submitDelete } from './theme-delete';

  let { data } = $props();
  let { preview, public_id } = $derived(data);

  let blockedReferrers = $derived(preview.blocked_by ?? []);

  let blocked = $derived<BlockedState | null>(
    blockedReferrers.length > 0
      ? {
          kind: 'referrers',
          lead: "This theme can't be deleted because active records still point at it:",
          referrers: blockedReferrers,
          renderReferrerHref: () => null,
          renderReferrerHint: (r: BlockingReferrer) => `references this theme via ${r.relation}`,
          footer: 'Resolve these references, then try again.',
        }
      : null,
  );

  let impact = $derived({
    items: ['this theme', pluralize(preview.changeset_count, 'change set')],
    note: 'You can undo this from the toast that appears on the themes page, or restore the record later from its edit history.',
  });
</script>

<DeletePage
  entityLabel="Theme"
  entityName={preview.name}
  {public_id}
  submit={submitDelete}
  cancelHref={`/themes/${public_id}`}
  redirectAfterDelete="/themes"
  editHistoryHref={`/themes/${public_id}/edit-history`}
  {blocked}
  {impact}
/>
