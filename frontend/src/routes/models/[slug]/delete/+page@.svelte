<script lang="ts">
  import DeletePage from '$lib/components/pages/record/delete/DeletePage.svelte';
  import type { BlockedState } from '$lib/components/pages/record/delete/delete-page';
  import { referrerHref, type BlockingReferrer } from '$lib/delete-flow';
  import { pluralize } from '$lib/utils';
  import { submitDelete } from './model-delete';

  let { data } = $props();
  let { preview, public_id } = $derived(data);

  let blockedReferrers = $derived(preview.blocked_by ?? []);

  let blocked = $derived<BlockedState | null>(
    blockedReferrers.length === 0
      ? null
      : {
          kind: 'referrers',
          lead: "This model can't be deleted because active records still point at it:",
          referrers: blockedReferrers,
          renderReferrerHref: referrerHref,
          renderReferrerHint: (r: BlockingReferrer) => `references this model via ${r.relation}`,
          footer: 'Resolve these references, then try again.',
        },
  );

  let impact = $derived({
    items: ['this model', pluralize(preview.changeset_count, 'change set')],
    note: 'You can undo this from the toast that appears on the title page, or restore the record later from its edit history.',
  });
</script>

<DeletePage
  entityLabel="Model"
  entityName={preview.name}
  {public_id}
  submit={submitDelete}
  cancelHref={`/models/${public_id}`}
  redirectAfterDelete={`/titles/${preview.parent.public_id}`}
  editHistoryHref={`/models/${public_id}/edit-history`}
  parentBreadcrumb={{ text: preview.parent.name, href: `/titles/${preview.parent.public_id}` }}
  {blocked}
  {impact}
/>
