<script lang="ts">
  import { untrack } from 'svelte';
  import SearchableSelect from '$lib/components/input/SearchableSelect.svelte';
  import { diffScalarFields } from '$lib/edit-helpers';
  import type { SectionEditorProps } from '$lib/components/pages/record/edit/editors/editor-contract';
  import {
    EMPTY_EDIT_OPTIONS,
    fetchModelEditOptions,
    toSelectOptions,
    type ModelEditOptions,
  } from './model-edit-options';
  import type { FieldErrors } from '$lib/api/parse-api-error';
  import { saveModelClaims, type SaveResult, type SaveMeta } from './save-model-claims';

  const TECHNOLOGY_FIELDS = [
    {
      field: 'technology_generation',
      optionsKey: 'technology_generations',
      label: 'Technology generation',
    },
    {
      field: 'technology_subgeneration',
      optionsKey: 'technology_subgenerations',
      label: 'Technology subgeneration',
    },
    { field: 'display_type', optionsKey: 'display_types', label: 'Display type' },
    { field: 'display_subtype', optionsKey: 'display_subtypes', label: 'Display subtype' },
    { field: 'system', optionsKey: 'systems', label: 'System' },
  ] as const;

  type TechnologyModel = {
    technology_generation?: { public_id: string } | null;
    technology_subgeneration?: { public_id: string } | null;
    system?: { public_id: string } | null;
    display_type?: { public_id: string } | null;
    display_subtype?: { public_id: string } | null;
  };

  let { initialData, slug, onsaved, onerror }: SectionEditorProps<TechnologyModel> = $props();

  type TechnologyFormFields = {
    technology_generation: string;
    technology_subgeneration: string;
    system: string;
    display_type: string;
    display_subtype: string;
  };

  function extractFields(m: TechnologyModel): TechnologyFormFields {
    return {
      technology_generation: m.technology_generation?.public_id ?? '',
      technology_subgeneration: m.technology_subgeneration?.public_id ?? '',
      system: m.system?.public_id ?? '',
      display_type: m.display_type?.public_id ?? '',
      display_subtype: m.display_subtype?.public_id ?? '',
    };
  }

  // untrack: intentional one-time capture; component re-mounts when modal reopens
  const original = untrack(() => extractFields(initialData));
  let fields = $state<TechnologyFormFields>({ ...original });
  let dirty = $derived.by(() => Object.keys(diffScalarFields(fields, original)).length > 0);

  let fieldErrors = $state<FieldErrors>({});
  let editOptions = $state<ModelEditOptions>(EMPTY_EDIT_OPTIONS);

  $effect(() => {
    fetchModelEditOptions().then((opts) => {
      editOptions = opts;
    });
  });

  export { dirty };

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

<div class="technology-grid">
  {#each TECHNOLOGY_FIELDS as fk (fk.field)}
    <SearchableSelect
      label={fk.label}
      options={toSelectOptions(editOptions[fk.optionsKey] ?? [])}
      bind:selected={fields[fk.field]}
      error={fieldErrors[fk.field] ?? ''}
      allowZeroCount
      showCounts={false}
      placeholder="Search {fk.label.toLowerCase()}..."
    />
  {/each}
</div>

<style>
  .technology-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
    gap: var(--size-3);
  }
</style>
