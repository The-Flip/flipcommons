<script lang="ts">
  import { untrack } from 'svelte';
  import TextField from '$lib/components/input/TextField.svelte';
  import type { SectionEditorProps } from '$lib/components/editors/editor-contract';
  import { diffScalarFields } from '$lib/edit-helpers';
  import type { ManufacturerEditView } from './manufacturer-edit-types';
  import type { FieldErrors } from '$lib/api/parse-api-error';
  import {
    saveManufacturerClaims,
    type SaveMeta,
    type SaveResult,
  } from './save-manufacturer-claims';

  type BasicsFields = {
    website: string;
    logo_url: string;
  };

  let {
    initialData,
    slug,
    onsaved,
    onerror,
    ondirtychange = () => {},
  }: SectionEditorProps<ManufacturerEditView> = $props();

  function extractFields(manufacturer: ManufacturerEditView): BasicsFields {
    return {
      website: manufacturer.website ?? '',
      logo_url: manufacturer.logo_url ?? '',
    };
  }

  const original = untrack(() => extractFields(initialData));
  let fields = $state<BasicsFields>({ ...original });
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

    const result: SaveResult = await saveManufacturerClaims(slug, {
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
  <TextField
    label="Website"
    bind:value={fields.website}
    type="url"
    error={fieldErrors.website ?? ''}
  />
  <TextField
    label="Logo URL"
    bind:value={fields.logo_url}
    type="url"
    error={fieldErrors.logo_url ?? ''}
  />
</div>

<style>
  .editor-fields {
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
  }
</style>
