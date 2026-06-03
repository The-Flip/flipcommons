<script lang="ts">
  import { untrack } from 'svelte';
  import MarkdownTextArea from '$lib/components/input/markdown/MarkdownTextArea.svelte';
  import type { SectionEditorProps } from './editor-contract';
  import type { FieldErrors } from '$lib/api/parse-api-error';
  import type { SaveMeta, SaveResult } from './save-claims-shared';

  type SaveFn = (
    slug: string,
    body: { fields: { description: string } } & SaveMeta,
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
      ...meta,
    });

    if (result.ok) {
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
  />
</div>

<style>
  .editor-fields {
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
  }
</style>
