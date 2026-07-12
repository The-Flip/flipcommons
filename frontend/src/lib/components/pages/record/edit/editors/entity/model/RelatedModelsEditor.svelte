<script lang="ts">
  import { untrack } from 'svelte';
  import EntitySelect from '$lib/components/input/entity-select/EntitySelect.svelte';
  import type { EntityOption } from '$lib/api/entity-autocomplete';
  import { diffScalarFields } from '$lib/edit-helpers';
  import type { SectionEditorProps } from '$lib/components/pages/record/edit/editors/editor-contract';
  import type { FieldErrors } from '$lib/api/parse-api-error';
  import { saveModelClaims, type SaveResult, type SaveMeta } from './save-model-claims';

  const HIERARCHY_FIELDS = [
    { field: 'variant_of', label: 'Variant of' },
    { field: 'converted_from', label: 'Converted from' },
    { field: 'remake_of', label: 'Remake of' },
    { field: 'bootleg_of', label: 'Bootleg of' },
    { field: 'licensed_build_of', label: 'Licensed build of' },
  ] as const;

  type HierarchyField = (typeof HIERARCHY_FIELDS)[number]['field'];
  type HierarchyRef = { public_id: string; name?: string } | null | undefined;

  type RelatedModelsModel = {
    variant_of?: HierarchyRef;
    converted_from?: HierarchyRef;
    remake_of?: HierarchyRef;
    bootleg_of?: HierarchyRef;
    licensed_build_of?: HierarchyRef;
  };

  let {
    initialData,
    slug,
    onsaved,
    onerror,
    ondirtychange = () => {},
  }: SectionEditorProps<RelatedModelsModel> = $props();

  // Flatten nested FK objects to slug strings for form state ('' = none).
  const original = untrack(() => ({
    variant_of: initialData.variant_of?.public_id ?? '',
    converted_from: initialData.converted_from?.public_id ?? '',
    remake_of: initialData.remake_of?.public_id ?? '',
    bootleg_of: initialData.bootleg_of?.public_id ?? '',
    licensed_build_of: initialData.licensed_build_of?.public_id ?? '',
  }));

  let fieldErrors = $state<FieldErrors>({});
  // Bound as `string | null` (the widget clears to null); normalize null → ''
  // at the diff boundary so a cleared FK diffs as '' → null.
  let fields = $state<Record<HierarchyField, string | null>>({ ...original });
  let current = $derived({
    variant_of: fields.variant_of ?? '',
    converted_from: fields.converted_from ?? '',
    remake_of: fields.remake_of ?? '',
    bootleg_of: fields.bootleg_of ?? '',
    licensed_build_of: fields.licensed_build_of ?? '',
  });
  let dirty = $derived.by(() => Object.keys(diffScalarFields(current, original)).length > 0);

  function initialSelection(ref: HierarchyRef): EntityOption | null {
    return ref ? { value: ref.public_id, label: ref.name ?? ref.public_id } : null;
  }

  $effect(() => {
    ondirtychange(dirty);
  });

  export function isDirty(): boolean {
    return dirty;
  }

  export async function save(meta?: SaveMeta): Promise<void> {
    fieldErrors = {};
    const changed = diffScalarFields(current, original);

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
    <EntitySelect
      type="model"
      {label}
      bind:selected={fields[field]}
      initialSelection={initialSelection(initialData[field])}
      exclude={[slug]}
      error={fieldErrors[field] ?? ''}
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
