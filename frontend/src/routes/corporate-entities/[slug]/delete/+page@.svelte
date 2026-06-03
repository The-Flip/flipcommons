<script lang="ts">
  import DeletePage from '$lib/components/pages/record/delete/DeletePage.svelte';
  import type { BlockedState } from '$lib/components/pages/record/delete/delete-page';
  import type { BlockingReferrer } from '$lib/delete-flow';
  import { pluralize } from '$lib/utils';
  import { submitDelete } from './corporate-entity-delete';

  let { data } = $props();
  let { preview, public_id } = $derived(data);

  let blockedReferrers = $derived(preview.blocked_by ?? []);

  function referrerHref(r: BlockingReferrer): string | null {
    if (!r.slug) return null;
    if (r.entity_type === 'model') return `/models/${r.slug}`;
    return null;
  }

  let blocked = $derived<BlockedState | null>(
    blockedReferrers.length > 0
      ? {
          kind: 'referrers',
          lead: "This corporate entity can't be deleted because active records still point at it:",
          referrers: blockedReferrers,
          renderReferrerHref: referrerHref,
          renderReferrerHint: (r: BlockingReferrer) =>
            `references this corporate entity via ${r.relation}`,
          footer: 'Resolve these references, then try again.',
        }
      : null,
  );

  let impact = $derived({
    items: ['this corporate entity', pluralize(preview.changeset_count, 'change set')],
    note: 'You can undo this from the toast that appears on the manufacturer page, or restore the record later from its edit history.',
  });
</script>

<DeletePage
  entityLabel="Corporate Entity"
  entityName={preview.name}
  {public_id}
  submit={submitDelete}
  cancelHref={`/corporate-entities/${public_id}`}
  redirectAfterDelete={preview.parent
    ? `/manufacturers/${preview.parent.public_id}`
    : '/corporate-entities'}
  editHistoryHref={`/corporate-entities/${public_id}/edit-history`}
  parentBreadcrumb={preview.parent
    ? { text: preview.parent.name, href: `/manufacturers/${preview.parent.public_id}` }
    : undefined}
  {blocked}
  {impact}
/>
