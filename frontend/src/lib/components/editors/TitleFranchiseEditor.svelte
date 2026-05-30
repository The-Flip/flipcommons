<script lang="ts">
  import { untrack } from 'svelte';
  import SearchableSelect from '$lib/components/SearchableSelect.svelte';
  import { diffScalarFields } from '$lib/edit-helpers';
  import type { SectionEditorProps } from './editor-contract';
  import type { FieldErrors } from '$lib/api/parse-api-error';
  import type { SaveResult, SaveMeta } from './save-claims-shared';
  import { saveTitleClaims } from './save-title-claims';
  import {
    fetchFranchiseOptions,
    fetchSeriesOptions,
    type TitleEditOption,
  } from './title-edit-options';

  type FranchiseTitle = {
    franchise?: { public_id: string } | null;
    series?: { public_id: string } | null;
  };

  let {
    initialData,
    slug,
    onsaved,
    onerror,
    ondirtychange = () => {},
  }: SectionEditorProps<FranchiseTitle> = $props();

  type FranchiseFormFields = {
    franchise: string;
    series: string;
  };

  function extractFields(t: FranchiseTitle): FranchiseFormFields {
    return {
      franchise: t.franchise?.public_id ?? '',
      series: t.series?.public_id ?? '',
    };
  }

  const original = untrack(() => extractFields(initialData));
  let fields = $state<FranchiseFormFields>({ ...original });
  let dirty = $derived(Object.keys(diffScalarFields(fields, original)).length > 0);

  let fieldErrors = $state<FieldErrors>({});

  let franchiseOptions = $state<TitleEditOption[]>([]);
  let seriesOptions = $state<TitleEditOption[]>([]);

  $effect(() => {
    fetchFranchiseOptions().then((opts) => (franchiseOptions = opts));
  });

  $effect(() => {
    fetchSeriesOptions().then((opts) => (seriesOptions = opts));
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

    const result: SaveResult = await saveTitleClaims(slug, {
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

<div class="franchise-grid">
  <SearchableSelect
    label="Franchise"
    options={franchiseOptions}
    bind:selected={fields.franchise}
    error={fieldErrors.franchise ?? ''}
    allowZeroCount
    placeholder="Search franchises..."
  />
  <SearchableSelect
    label="Series"
    options={seriesOptions}
    bind:selected={fields.series}
    error={fieldErrors.series ?? ''}
    allowZeroCount
    placeholder="Search series..."
  />
</div>

<style>
  .franchise-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--size-3);
  }
</style>
