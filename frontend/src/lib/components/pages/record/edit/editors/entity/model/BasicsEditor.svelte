<script lang="ts">
  import { untrack } from 'svelte';
  import SearchableSelect from '$lib/components/input/SearchableSelect.svelte';
  import NumberField from '$lib/components/input/NumberField.svelte';
  import MonthSelect from '$lib/components/input/MonthSelect.svelte';
  import { fetchFieldConstraints, fc, type FieldConstraints } from '$lib/field-constraints';
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

  type BasicsModel = {
    year?: number | null;
    month?: number | null;
    title?: { public_id: string } | null;
    corporate_entity?: { public_id: string } | null;
  };

  // `slim` hides the Title picker. Used on single-model combined edit, where
  // re-picking the title isn't allowed — the "Change Title" affordance is
  // deferred to its own section. Manufacturer/Year/Month always show.
  let {
    initialData,
    slug,
    onsaved,
    onerror,
    ondirtychange = () => {},
    slim = false,
  }: SectionEditorProps<BasicsModel> & { slim?: boolean } = $props();

  type BasicsFormFields = {
    year: string | number;
    month: string | number;
    title: string;
    corporate_entity: string;
  };

  function extractFields(m: BasicsModel): BasicsFormFields {
    return {
      year: m.year ?? '',
      month: m.month ?? '',
      title: m.title?.public_id ?? '',
      corporate_entity: m.corporate_entity?.public_id ?? '',
    };
  }

  // untrack: intentional one-time capture; component re-mounts when modal reopens
  const original = untrack(() => extractFields(initialData));
  let fields = $state<BasicsFormFields>({ ...original });
  // Hidden fields (slim mode) never mutate because they have no UI, so
  // diffScalarFields naturally ignores them — no explicit strip needed.
  let dirty = $derived(Object.keys(diffScalarFields(fields, original)).length > 0);

  let fieldErrors = $state<FieldErrors>({});
  let editOptions = $state<ModelEditOptions>(EMPTY_EDIT_OPTIONS);
  let constraints = $state<FieldConstraints>({});

  $effect(() => {
    fetchFieldConstraints('model').then((c) => {
      constraints = c;
    });
  });

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

<div class="basics-grid">
  {#if !slim}
    <!--
			TODO: title is required (NOT NULL on MachineModel), but SearchableSelect's
			built-in ✕ button still lets users clear it locally. Saving triggers a
			backend 422 that renders inline, so the invariant holds — but the UX is
			"click clear, try to save, see error" instead of "can't clear at all".
			Follow-up: add a `required` prop to SearchableSelect that hides the ✕.
		-->
    <SearchableSelect
      label="Title"
      options={toSelectOptions(editOptions.titles ?? [])}
      bind:selected={fields.title}
      error={fieldErrors.title ?? ''}
      showCounts={false}
      placeholder="Search titles..."
    />
  {/if}
  <SearchableSelect
    label="Manufacturer"
    options={toSelectOptions(editOptions.corporate_entities ?? [])}
    bind:selected={fields.corporate_entity}
    error={fieldErrors.corporate_entity ?? ''}
    allowZeroCount
    showCounts={false}
    placeholder="Search manufacturers..."
  />
  <NumberField
    label="Year"
    bind:value={fields.year}
    error={fieldErrors.year ?? ''}
    {...fc(constraints, 'year')}
  />
  <MonthSelect label="Month" bind:value={fields.month} error={fieldErrors.month ?? ''} />
</div>

<style>
  .basics-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--size-3);
  }
</style>
