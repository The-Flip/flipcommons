<script lang="ts">
  import { untrack } from 'svelte';
  import SearchableSelect from '$lib/components/input/SearchableSelect.svelte';
  import { diffScalarFields } from '$lib/edit-helpers';
  import type { SectionEditorProps } from '$lib/components/pages/record/edit/editors/editor-contract';
  import type { FieldErrors } from '$lib/api/parse-api-error';
  import type {
    SaveMeta,
    SaveResult,
  } from '$lib/components/pages/record/edit/editors/save-claims-shared';
  import { fetchManufacturerOptions, type SystemEditOption } from './system-edit-options';

  type ManufacturerFields = {
    manufacturer: string;
  };

  type SaveFn = (
    slug: string,
    body: { fields: Partial<ManufacturerFields> } & SaveMeta,
  ) => Promise<SaveResult>;

  type InitialData = {
    manufacturer?: { public_id: string } | null;
  };

  let {
    initialData,
    slug,
    save: saveFn,
    onsaved,
    onerror,
    ondirtychange = () => {},
  }: SectionEditorProps<InitialData> & { save: SaveFn } = $props();

  const original = untrack(() => ({
    manufacturer: initialData.manufacturer?.public_id ?? '',
  }));
  let fields = $state<ManufacturerFields>({ ...original });
  let fieldErrors = $state<FieldErrors>({});
  let options = $state<SystemEditOption[]>([]);
  let dirty = $derived(Object.keys(diffScalarFields(fields, original)).length > 0);

  $effect(() => {
    fetchManufacturerOptions().then((opts) => (options = opts));
  });

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

    const changed = diffScalarFields(fields, original);
    const result = await saveFn(slug, { fields: changed, ...meta });

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

<SearchableSelect
  label="Manufacturer"
  {options}
  bind:selected={fields.manufacturer}
  error={fieldErrors.manufacturer ?? ''}
  allowZeroCount
  showCounts={false}
  placeholder="Search manufacturers..."
/>
