<script lang="ts">
  import { untrack } from 'svelte';
  import NumberField from '$lib/components/input/NumberField.svelte';
  import type { SectionEditorProps } from '$lib/components/pages/record/edit/editors/editor-contract';
  import { diffScalarFields } from '$lib/edit-helpers';
  import type { FieldErrors } from '$lib/api/parse-api-error';
  import type {
    SaveMeta,
    SaveResult,
  } from '$lib/components/pages/record/edit/editors/save-claims-shared';

  type DisplayOrderFields = {
    display_order: string | number;
  };

  type SaveFn = (
    slug: string,
    body: { fields: Partial<DisplayOrderFields> } & SaveMeta,
  ) => Promise<SaveResult>;

  let {
    initialData,
    slug,
    save: saveFn,
    onsaved,
    onerror,
    ondirtychange = () => {},
  }: SectionEditorProps<number | null> & { save: SaveFn } = $props();

  const original = untrack<DisplayOrderFields>(() => ({
    display_order: initialData ?? '',
  }));
  let fields = $state<DisplayOrderFields>({ ...original });
  let fieldErrors = $state<FieldErrors>({});
  let changedFields = $derived(diffScalarFields(fields, original));
  let dirty = $derived(Object.keys(changedFields).length > 0);

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
      fields: changedFields,
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
  <NumberField
    label="Display order"
    bind:value={fields.display_order}
    error={fieldErrors.display_order ?? ''}
  />
</div>

<style>
  .editor-fields {
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
  }
</style>
