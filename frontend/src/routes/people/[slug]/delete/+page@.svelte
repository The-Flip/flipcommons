<script lang="ts">
  import DeletePage from '$lib/components/pages/record/delete/DeletePage.svelte';
  import type { BlockedState } from '$lib/components/pages/record/delete/delete-page';
  import type { BlockingReferrer } from '$lib/delete-flow';
  import { pluralize } from '$lib/utils';
  import { submitDelete } from './person-delete';

  let { data } = $props();
  let { preview, public_id } = $derived(data);

  let blockedReferrers = $derived(preview.blocked_by ?? []);
  let activeCreditCount = $derived(preview.active_credit_count);

  // Two separate block mechanisms:
  //  - active credits (Person-specific): just a count, no per-referrer list.
  //  - generic PROTECT blockers: rendered as a list (none expected today).
  let blocked = $derived<BlockedState | null>(
    activeCreditCount > 0
      ? {
          kind: 'message',
          lead: `${preview.name} is credited on ${pluralize(
            activeCreditCount,
            'active machine',
          )}. Remove those credits from the machine(s) before deleting this person.`,
        }
      : blockedReferrers.length > 0
        ? {
            kind: 'referrers',
            lead: "This person can't be deleted because active records still point at them:",
            referrers: blockedReferrers,
            renderReferrerHref: () => null,
            renderReferrerHint: (r: BlockingReferrer) => `references this person via ${r.relation}`,
            footer: 'Resolve these references, then try again.',
          }
        : null,
  );

  let impact = $derived({
    items: ['this person', pluralize(preview.changeset_count, 'change set')],
    note: 'You can undo this from the toast that appears on the people page, or restore the record later from its edit history.',
  });
</script>

<DeletePage
  entityLabel="Person"
  entityName={preview.name}
  {public_id}
  submit={submitDelete}
  cancelHref={`/people/${public_id}`}
  redirectAfterDelete="/people"
  editHistoryHref={`/people/${public_id}/edit-history`}
  {blocked}
  {impact}
/>
