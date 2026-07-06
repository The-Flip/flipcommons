<script lang="ts">
  import { untrack } from 'svelte';
  import MarkdownTextArea from '$lib/components/input/markdown/MarkdownTextArea.svelte';
  import InlineCitationsPanel from '$lib/components/input/citation/InlineCitationsPanel.svelte';
  import { buildInlineCitationsRequest, type PendingInlineCitation } from '$lib/pending-citations';
  import type { InlineCitationSpecSchema } from '$lib/api/schema';
  import type { SectionEditorProps } from './editor-contract';
  import type { FieldErrors } from '$lib/api/parse-api-error';
  import type { SaveMeta, SaveResult } from './save-claims-shared';

  type SaveFn = (
    slug: string,
    body: {
      fields: { description: string };
      inline_citations: InlineCitationSpecSchema[];
    } & SaveMeta,
  ) => Promise<SaveResult>;

  let {
    initialData,
    slug,
    save: saveFn,
    label = 'Description',
    onsaved,
    onerror,
    ondirtychange = () => {},
  }: SectionEditorProps<string> & { save: SaveFn; label?: string } = $props();

  const original = untrack(() => initialData);
  let description = $state(original);
  let fieldErrors = $state<FieldErrors>({});
  let dirty = $derived(description !== original);

  // Content specs for the [[cite:slug]] markers inserted this session,
  // editable in the panel below until save. Entries whose marker was deleted
  // from the text stay here harmlessly (hidden, pruned from the payload) so
  // an undo that restores the marker restores its spec too.
  let pendingCitations = $state<PendingInlineCitation[]>([]);

  $effect(() => {
    ondirtychange(dirty);
  });

  export function isDirty(): boolean {
    return dirty;
  }

  export async function save(meta?: SaveMeta): Promise<void> {
    fieldErrors = {};
    if (!dirty) {
      onsaved();
      return;
    }

    const result = await saveFn(slug, {
      fields: { description },
      inline_citations: buildInlineCitationsRequest(pendingCitations, description),
      ...meta,
    });

    if (result.ok) {
      // The saved specs are minted instances now; re-sending them on a later
      // save in this session would be rejected as already consumed.
      pendingCitations = [];
      onsaved();
    } else {
      fieldErrors = result.fieldErrors;
      onerror(
        Object.keys(result.fieldErrors).length > 0 ? 'Please fix the errors below.' : result.error,
      );
    }
  }
</script>

<div class="editor-fields">
  <MarkdownTextArea
    {label}
    bind:value={description}
    rows={8}
    error={fieldErrors.description ?? ''}
    onpendingcitation={(pending) => (pendingCitations = [...pendingCitations, pending])}
  />
  <InlineCitationsPanel pending={pendingCitations} text={description} />
</div>

<style>
  .editor-fields {
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
  }
</style>
