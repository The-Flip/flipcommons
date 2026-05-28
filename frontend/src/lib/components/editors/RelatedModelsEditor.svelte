<script lang="ts">
  import { untrack } from 'svelte';
  import SearchableSelect from '$lib/components/SearchableSelect.svelte';
  import { diffScalarFields } from '$lib/edit-helpers';
  import type { SectionEditorProps } from './editor-contract';
  import {
    EMPTY_EDIT_OPTIONS,
    fetchModelEditOptions,
    type ModelEditOptions,
  } from './model-edit-options';
  import type { FieldErrors } from '$lib/api/parse-api-error';
  import { saveModelClaims, type SaveResult, type SaveMeta } from './save-model-claims';

  const HIERARCHY_FIELDS = [
    { field: 'variant_of', label: 'Variant of' },
    { field: 'converted_from', label: 'Converted from' },
    { field: 'remake_of', label: 'Remake of' },
  ] as const;

  type HierarchyRef = { public_id: string; name?: string } | null | undefined;

  type RelatedModelsModel = {
    variant_of?: HierarchyRef;
    converted_from?: HierarchyRef;
    remake_of?: HierarchyRef;
  };

  let {
    initialData,
    slug,
    onsaved,
    onerror,
    ondirtychange = () => {},
  }: SectionEditorProps<RelatedModelsModel> = $props();

  // Flatten nested FK objects to slug strings for form state
  const original = untrack(() => ({
    variant_of: initialData.variant_of?.public_id ?? '',
    converted_from: initialData.converted_from?.public_id ?? '',
    remake_of: initialData.remake_of?.public_id ?? '',
  }));

  let fieldErrors = $state<FieldErrors>({});
  let fields = $state({ ...original });
  let dirty = $derived.by(() => Object.keys(diffScalarFields(fields, original)).length > 0);

  let editOptions = $state<ModelEditOptions>(EMPTY_EDIT_OPTIONS);

  // Filter out the current model from the options list
  let modelOptions = $derived((editOptions.models ?? []).filter((o) => o.slug !== slug));

  $effect(() => {
    fetchModelEditOptions().then((opts) => {
      editOptions = opts;
    });
  });

  $effect(() => {
    ondirtychange(dirty);
  });

  export function isDirty(): boolean {
    return dirty;
  }

  export async function save(meta?: SaveMeta): Promise<void> {
    fieldErrors = {};
    const changed = diffScalarFields(fields, original);

    if (!dirty) {
      onsaved();
      return;
    }

    const result: SaveResult = await saveModelClaims(slug, {
      fields: changed,
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

<div class="related-models-editor">
  {#each HIERARCHY_FIELDS as { field, label } (field)}
    <SearchableSelect
      {label}
      options={modelOptions}
      bind:selected={fields[field]}
      error={fieldErrors[field] ?? ''}
      allowZeroCount
      showCounts={false}
      placeholder="Search models..."
    />
  {/each}
</div>

<style>
  .related-models-editor {
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
  }
</style>
