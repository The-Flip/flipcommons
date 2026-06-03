<script lang="ts">
  import DeletePage from '$lib/components/pages/record/delete/DeletePage.svelte';
  import type { BlockedState } from '$lib/components/pages/record/delete/delete-page';
  import type { BlockingReferrer } from '$lib/delete-flow';
  import { pluralize } from '$lib/utils';
  import { submitDelete } from './location-delete';

  let { data } = $props();
  let { preview, public_id } = $derived(data);

  let blockedReferrers = $derived(preview.blocked_by ?? []);
  let activeChildren = $derived(preview.active_children_count ?? 0);

  let blocked = $derived<BlockedState | null>(
    activeChildren > 0
      ? {
          kind: 'message',
          lead: `${preview.name} has ${pluralize(activeChildren, 'active child location')}. Delete those first.`,
        }
      : blockedReferrers.length > 0
        ? {
            kind: 'referrers',
            lead: "This location can't be deleted because active corporate-entity locations still point at it:",
            referrers: blockedReferrers,
            renderReferrerHref: (r: BlockingReferrer) =>
              r.slug ? `/corporate-entities/${r.slug}` : null,
            renderReferrerHint: (r: BlockingReferrer) =>
              `references this location via ${r.relation}`,
            footer: 'Resolve these references, then try again.',
          }
        : null,
  );

  // Country → /locations; child → parent's detail page (strip last segment).
  let parentPath = $derived.by(() => {
    const idx = public_id.lastIndexOf('/');
    return idx >= 0 ? public_id.slice(0, idx) : '';
  });
  let redirectAfterDelete = $derived(parentPath ? `/locations/${parentPath}` : '/locations');

  let impact = $derived({
    items: [
      'this location only — child locations are unaffected',
      pluralize(preview.changeset_count, 'change set'),
    ],
    note: 'You can undo this from the toast that appears on the location page, or restore the record later from its edit history.',
  });
</script>

<DeletePage
  entityLabel="Location"
  entityName={preview.name}
  {public_id}
  submit={submitDelete}
  cancelHref={`/locations/${public_id}`}
  {redirectAfterDelete}
  editHistoryHref={`/locations/${public_id}/edit-history`}
  {blocked}
  {impact}
/>
