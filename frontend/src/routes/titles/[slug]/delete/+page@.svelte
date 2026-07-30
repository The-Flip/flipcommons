<script lang="ts">
  import DeletePage from '$lib/components/pages/record/delete/DeletePage.svelte';
  import type { BlockedState } from '$lib/components/pages/record/delete/delete-page';
  import { referrerHref, type BlockingReferrer } from '$lib/delete-flow';
  import { pluralize } from '$lib/utils';
  import { submitDelete } from './title-delete';

  let { data } = $props();
  let { preview, public_id } = $derived(data);

  let blockedReferrers = $derived(preview.blocked_by ?? []);

  let blocked = $derived<BlockedState | null>(
    blockedReferrers.length === 0
      ? null
      : {
          kind: 'referrers',
          lead: `This title can't be deleted because active records still point at ${
            blockedReferrers.length === 1 ? 'it' : 'parts of it'
          }:`,
          referrers: blockedReferrers,
          renderReferrerHref: referrerHref,
          renderReferrerHint: (r: BlockingReferrer) =>
            `references ${r.blocked_target_public_id} via ${r.relation}`,
          footer: 'Resolve these references, then try again.',
        },
  );

  let impact = $derived({
    items: [
      pluralize(preview.active_model_count, 'model'),
      pluralize(preview.changeset_count, 'change set'),
    ],
    note: 'You can undo this from the toast that appears on the titles list, or restore the record later from its edit history.',
  });
</script>

<DeletePage
  entityLabel="Title"
  entityName={preview.name}
  {public_id}
  submit={submitDelete}
  cancelHref={`/titles/${public_id}`}
  redirectAfterDelete="/titles"
  editHistoryHref={`/titles/${public_id}/edit-history`}
  {blocked}
  {impact}
/>
