<script lang="ts">
  import DeletePage from '$lib/components/pages/record/delete/DeletePage.svelte';
  import type {
    BlockedState,
    ParentBreadcrumb,
  } from '$lib/components/pages/record/delete/delete-page';
  import type { BlockingReferrer } from '$lib/delete-flow';
  import { pluralize } from '$lib/utils';
  import { submitDelete } from './technology-subgeneration-delete';

  let { data } = $props();
  let { preview, public_id } = $derived(data);

  let blockedReferrers = $derived(preview.blocked_by ?? []);

  let parentBreadcrumb = $derived<ParentBreadcrumb | undefined>(
    preview.parent
      ? {
          text: preview.parent.name,
          href: `/technology-generations/${preview.parent.public_id}`,
        }
      : undefined,
  );

  let blocked = $derived<BlockedState | null>(
    blockedReferrers.length > 0
      ? {
          kind: 'referrers',
          lead: "This subgeneration can't be deleted because active records still point at it:",
          referrers: blockedReferrers,
          renderReferrerHref: () => null,
          renderReferrerHint: (r: BlockingReferrer) =>
            `references this subgeneration via ${r.relation}`,
          footer: 'Resolve these references, then try again.',
        }
      : null,
  );

  let impact = $derived({
    items: ['this subgeneration', pluralize(preview.changeset_count, 'change set')],
    note: 'You can undo this from the toast that appears on the technology generations page, or restore the record later from its edit history.',
  });
</script>

<DeletePage
  entityLabel="Subgeneration"
  entityName={preview.name}
  {public_id}
  submit={submitDelete}
  cancelHref={`/technology-subgenerations/${public_id}`}
  redirectAfterDelete="/technology-generations"
  editHistoryHref={`/technology-subgenerations/${public_id}/edit-history`}
  {parentBreadcrumb}
  {blocked}
  {impact}
/>
