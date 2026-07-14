<script lang="ts">
  import { untrack } from 'svelte';
  import TagInput from '$lib/components/input/TagInput.svelte';
  import type { SectionEditorProps } from '$lib/components/pages/record/edit/editors/editor-contract';
  import type { FieldErrors } from '$lib/api/parse-api-error';
  import type { LocationEditView } from './location-edit-types';
  import { saveLocationClaims, type SaveMeta, type SaveResult } from './save-location-claims';

  let {
    initialData,
    slug: publicId,
    onsaved,
    onerror,
  }: SectionEditorProps<LocationEditView> = $props();

  const originalDivisions = untrack(() => [...(initialData.divisions ?? [])]);
  let divisions = $state<string[]>([...originalDivisions]);
  let fieldErrors = $state<FieldErrors>({});
  // Order matters (divisions[0] names the country's first child tier),
  // so use index-sensitive equality rather than the order-independent
  // `stringSetChanged` helper.
  let dirty = $derived(
    divisions.length !== originalDivisions.length ||
      divisions.some((v, i) => v !== originalDivisions[i]),
  );

  export { dirty };

  export async function save(meta?: SaveMeta): Promise<void> {
    fieldErrors = {};
    if (!dirty) {
      onsaved();
      return;
    }

    const result: SaveResult = await saveLocationClaims(publicId, {
      divisions,
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
  <p class="hint">
    Division labels for child tiers, ordered from country down (e.g. <code>state</code>,
    <code>city</code>). The first label names the next tier of children under this country.
  </p>
  <TagInput
    label="Divisions"
    bind:tags={divisions}
    placeholder="Type a division and press Enter"
    error={fieldErrors.divisions ?? ''}
  />
</div>

<style>
  .editor-fields {
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
  }
  .hint {
    margin: 0;
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
  }
</style>
