<script lang="ts">
  import { untrack } from 'svelte';
  import EntitySelect from '$lib/components/input/entity-select/EntitySelect.svelte';
  import type { EntityOption } from '$lib/api/entity-autocomplete';
  import { diffScalarFields } from '$lib/edit-helpers';
  import type { SectionEditorProps } from '$lib/components/pages/record/edit/editors/editor-contract';
  import type { FieldErrors } from '$lib/api/parse-api-error';
  import type {
    SaveMeta,
    SaveResult,
  } from '$lib/components/pages/record/edit/editors/save-claims-shared';

  type ManufacturerFields = {
    manufacturer: string;
  };

  type SaveFn = (
    slug: string,
    body: { fields: Partial<ManufacturerFields> } & SaveMeta,
  ) => Promise<SaveResult>;

  // `manufacturer` is a required FK; the detail schema ships it as an
  // `EntityRef` ({ name, public_id }), so `name` seeds the typeahead's label.
  type InitialData = {
    manufacturer?: { public_id: string; name: string } | null;
  };

  let {
    initialData,
    slug,
    save: saveFn,
    onsaved,
    onerror,
  }: SectionEditorProps<InitialData> & { save: SaveFn } = $props();

  const original = untrack(() => ({
    manufacturer: initialData.manufacturer?.public_id ?? '',
  }));
  let fields = $state<ManufacturerFields>({ ...original });
  let fieldErrors = $state<FieldErrors>({});
  let dirty = $derived(Object.keys(diffScalarFields(fields, original)).length > 0);

  export { dirty };

  // Seed the typeahead so the saved manufacturer renders on mount with no search.
  const initialSelection: EntityOption | null = untrack(() =>
    initialData.manufacturer
      ? { value: initialData.manufacturer.public_id, label: initialData.manufacturer.name }
      : null,
  );

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

<EntitySelect
  type="manufacturer"
  label="Manufacturer"
  bind:selected={fields.manufacturer}
  {initialSelection}
  error={fieldErrors.manufacturer ?? ''}
  placeholder="Search manufacturers..."
  required
/>
