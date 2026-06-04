<script lang="ts">
  import { untrack } from 'svelte';
  import EntitySelect from '$lib/components/input/entity-select/EntitySelect.svelte';
  import type { EntityOption } from '$lib/api/entity-autocomplete';
  import { diffScalarFields } from '$lib/edit-helpers';
  import type { SectionEditorProps } from '$lib/components/pages/record/edit/editors/editor-contract';
  import type { FieldErrors } from '$lib/api/parse-api-error';
  import type {
    SaveResult,
    SaveMeta,
  } from '$lib/components/pages/record/edit/editors/save-claims-shared';
  import { saveTitleClaims } from './save-title-claims';

  // franchise/series are optional FKs; the detail schema ships each as an
  // `EntityRef` ({ name, public_id }), so `name` seeds the typeahead's label.
  type FranchiseRef = { public_id: string; name: string } | null | undefined;

  type FranchiseTitle = {
    franchise?: FranchiseRef;
    series?: FranchiseRef;
  };

  let {
    initialData,
    slug,
    onsaved,
    onerror,
    ondirtychange = () => {},
  }: SectionEditorProps<FranchiseTitle> = $props();

  // Original keeps the `''` sentinel for "none"; the form binds `string | null`
  // (the widget clears to `null`), normalized back to `''` at the diff boundary
  // so a cleared FK diffs as `'' → null` in the claim body.
  const original = untrack(() => ({
    franchise: initialData.franchise?.public_id ?? '',
    series: initialData.series?.public_id ?? '',
  }));
  let franchise = $state<string | null>(original.franchise || null);
  let series = $state<string | null>(original.series || null);
  let current = $derived({ franchise: franchise ?? '', series: series ?? '' });
  let dirty = $derived(Object.keys(diffScalarFields(current, original)).length > 0);

  let fieldErrors = $state<FieldErrors>({});

  function initialSelection(ref: FranchiseRef): EntityOption | null {
    return ref ? { value: ref.public_id, label: ref.name } : null;
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
  <EntitySelect
    type="franchise"
    label="Franchise"
    bind:selected={franchise}
    initialSelection={initialSelection(initialData.franchise)}
    error={fieldErrors.franchise ?? ''}
    placeholder="Search franchises..."
  />
  <EntitySelect
    type="series"
    label="Series"
    bind:selected={series}
    initialSelection={initialSelection(initialData.series)}
    error={fieldErrors.series ?? ''}
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
