<script lang="ts">
  import { untrack } from 'svelte';
  import TextField from '$lib/components/input/TextField.svelte';
  import type { SectionEditorProps } from '$lib/components/editors/editor-contract';
  import { diffScalarFields } from '$lib/edit-helpers';
  import type { FieldErrors } from '$lib/api/parse-api-error';
  import type { LocationEditView } from './location-edit-types';
  import { saveLocationClaims, type SaveMeta, type SaveResult } from './save-location-claims';

  type BasicsFields = {
    short_name: string;
    code: string;
  };

  let {
    initialData,
    slug: publicId,
    onsaved,
    onerror,
    ondirtychange = () => {},
  }: SectionEditorProps<LocationEditView> = $props();

  function extractFields(entity: LocationEditView): BasicsFields {
    return {
      short_name: entity.short_name ?? '',
      code: entity.code ?? '',
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

    const result: SaveResult = await saveLocationClaims(publicId, {
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
    label="Short name"
    bind:value={fields.short_name}
    optional
    placeholder="e.g. NYC"
    error={fieldErrors.short_name ?? ''}
  />
  <TextField
    label="Code"
    bind:value={fields.code}
    optional
    placeholder="e.g. US-NY"
    error={fieldErrors.code ?? ''}
  />
</div>

<style>
  .editor-fields {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--size-3);
  }
</style>
