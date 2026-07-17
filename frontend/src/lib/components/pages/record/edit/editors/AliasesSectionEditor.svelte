<script lang="ts">
  import { untrack } from 'svelte';
  import TagInput from '$lib/components/input/TagInput.svelte';
  import type { SectionEditorProps } from './editor-contract';
  import { stringSetChanged } from '$lib/edit-helpers';
  import type { FieldErrors } from '$lib/api/parse-api-error';
  import type { SaveMeta, SaveResult } from './save-claims-shared';

  type AliasesData = { aliases: string[] };

  type SaveBody = {
    aliases: string[];
  } & SaveMeta;

  type SaveFn = (slug: string, body: SaveBody) => Promise<SaveResult>;

  let {
    initialData,
    slug,
    save: saveFn,
    onsaved,
    onerror,
    placeholder = 'Type an alias and press Enter',
  }: SectionEditorProps<AliasesData> & {
    save: SaveFn;
    placeholder?: string;
  } = $props();

  const originalAliases = untrack(() => [...initialData.aliases]);
  let aliases = $state<string[]>([...originalAliases]);
  let fieldErrors = $state<FieldErrors>({});
  let dirty = $derived(stringSetChanged(aliases, originalAliases));

  export { dirty };

  export async function save(meta?: SaveMeta): Promise<void> {
    fieldErrors = {};
    if (!dirty) {
      onsaved();
      return;
    }

    const body: SaveBody = { aliases, ...meta };
    const result = await saveFn(slug, body);

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
  <TagInput label="Aliases" bind:tags={aliases} {placeholder} error={fieldErrors.aliases ?? ''} />
</div>

<style>
  .editor-fields {
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
  }
</style>
