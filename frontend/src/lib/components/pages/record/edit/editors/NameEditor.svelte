<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { untrack } from 'svelte';
  import TextField from '$lib/components/input/TextField.svelte';
  import TagInput from '$lib/components/input/TagInput.svelte';
  import type { SectionEditorProps } from './editor-contract';
  import { reconcileSlug, slugifyForCatalog } from '$lib/create-form';
  import { diffScalarFields, stringSetChanged } from '$lib/edit-helpers';
  import type { FieldErrors } from '$lib/api/parse-api-error';
  import type { SaveMeta, SaveResult } from './save-claims-shared';

  type NameFields = {
    name: string;
    slug: string;
  };

  type SaveBody = {
    fields?: Partial<NameFields>;
    abbreviations?: string[];
  } & SaveMeta;

  type SaveFn = (slug: string, body: SaveBody) => Promise<SaveResult>;

  let {
    initialData,
    initialAbbreviations,
    slug,
    save: saveFn,
    onsaved,
    onerror,
    ondirtychange = () => {},
  }: SectionEditorProps<NameFields> & {
    save: SaveFn;
    initialAbbreviations?: string[];
  } = $props();

  // Presence of the prop (even as `[]`) opts an entity into abbreviation editing.
  // Capture once via untrack: props are stable for this component's lifetime
  // (the modal remounts it on reopen) and Svelte's reactivity lint would
  // otherwise flag the direct read as capturing only the initial value.
  const supportsAbbreviations = untrack(() => initialAbbreviations !== undefined);
  const originalAbbreviations = untrack(() => [...(initialAbbreviations ?? [])]);

  const original = untrack(() => ({ ...initialData }));
  let fields = $state<NameFields>({ ...original });
  let abbreviations = $state<string[]>([...originalAbbreviations]);
  // Seeded with the projected slug (not the saved one) so that an editorially
  // customized slug starts out "pre-diverged" — reconcileSlug leaves it alone
  // until the user types a name whose projection matches the current slug.
  let syncedSlug = $state(slugifyForCatalog(original.name));
  let fieldErrors = $state<FieldErrors>({});
  let changedFields = $derived(diffScalarFields(fields, original));
  let abbreviationsDirty = $derived(
    supportsAbbreviations && stringSetChanged(abbreviations, originalAbbreviations),
  );
  let dirty = $derived(Object.keys(changedFields).length > 0 || abbreviationsDirty);

  $effect(() => {
    const next = reconcileSlug({ name: fields.name, slug: fields.slug, syncedSlug });
    if (next.slug !== fields.slug) {
      fields.slug = next.slug;
      syncedSlug = next.syncedSlug;
    }
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

    const body: SaveBody = { ...meta };
    if (Object.keys(changedFields).length > 0) {
      // Slugs are lowercase-only — casefold at submit so users see what they
      // typed while authoring and the backend SLUG_RE validator never trips.
      const submitFields = { ...changedFields };
      if (typeof submitFields.slug === 'string') {
        submitFields.slug = submitFields.slug.toLowerCase();
      }
      body.fields = submitFields;
    }
    if (abbreviationsDirty) body.abbreviations = abbreviations;

    const result = await saveFn(slug, body);

    if (result.ok) {
      if (result.updatedSlug && result.updatedSlug !== slug) {
        // Edit URLs are always /<resource>/<slug>/... so the slug sits at index 2.
        // Splitting and replacing by index avoids substring-match traps like
        // slug=`people` on `/people/people/edit/name` (where a regex anchored only
        // on the trailing boundary would corrupt the leading collection segment).
        const segments = page.url.pathname.split('/');
        segments[2] = result.updatedSlug;
        const nextPathname = segments.join('/');
        await goto(`${nextPathname}${page.url.search}`, { replaceState: true });
      }
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
  <TextField label="Name" bind:value={fields.name} error={fieldErrors.name ?? ''} />
  <TextField label="Slug" bind:value={fields.slug} error={fieldErrors.slug ?? ''} />
  {#if supportsAbbreviations}
    <TagInput label="Abbreviations" bind:tags={abbreviations} placeholder="Type and press Enter" />
  {/if}
</div>

<style>
  .editor-fields {
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
  }
</style>
