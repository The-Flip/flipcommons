<script lang="ts">
  import DeletePage from '$lib/components/pages/record/delete/DeletePage.svelte';
  import type { BlockedState } from '$lib/components/pages/record/delete/delete-page';
  import type { BlockingReferrer } from '$lib/delete-flow';
  import { pluralize } from '$lib/utils';
  import { submitDelete } from './technology-generation-delete';

  let { data } = $props();
  let { preview, public_id } = $derived(data);

  let blockedReferrers = $derived(preview.blocked_by ?? []);
  let activeChildren = $derived(preview.active_children_count ?? 0);

  let blocked = $derived<BlockedState | null>(
    activeChildren > 0
      ? {
          kind: 'message',
          lead: `${preview.name} has ${pluralize(activeChildren, 'active subgeneration')}. Delete those first.`,
        }
      : blockedReferrers.length > 0
        ? {
            kind: 'referrers',
            lead: "This technology generation can't be deleted because active records still point at it:",
            referrers: blockedReferrers,
            renderReferrerHref: () => null,
            renderReferrerHint: (r: BlockingReferrer) =>
              `references this technology generation via ${r.relation}`,
            footer: 'Resolve these references, then try again.',
          }
        : null,
  );

  let impact = $derived({
    items: ['this technology generation', pluralize(preview.changeset_count, 'change set')],
    note: 'You can undo this from the toast that appears on the technology generations page, or restore the record later from its edit history.',
  });
</script>

<DeletePage
  entityLabel="Technology Generation"
  entityName={preview.name}
  {public_id}
  submit={submitDelete}
  cancelHref={`/technology-generations/${public_id}`}
  redirectAfterDelete="/technology-generations"
  editHistoryHref={`/technology-generations/${public_id}/edit-history`}
  {blocked}
  {impact}
/>
