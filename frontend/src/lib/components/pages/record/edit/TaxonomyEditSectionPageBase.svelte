<!--
@component
Mobile full-page host for taxonomy section edits: resolves the active section
from the URL segment (redirecting to the default on mobile when none matches),
then delegates the editor lifecycle and footer chrome to SectionEditHarness.
Callers supply the entity editor switch as the `editor` snippet.
-->
<script lang="ts" generics="TKey extends string">
  import type { Snippet } from 'svelte';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { resolveHref } from '$lib/utils';
  import SectionEditHarness from './SectionEditHarness.svelte';
  import { WIDE_BREAKPOINT } from '$lib/constants';
  import type { EditSectionDef } from '$lib/components/pages/record/edit/editors/edit-section-def';
  import type { EditorCallbacks } from '$lib/components/pages/record/edit/editors/editor-callbacks';
  import { createBelowBreakpointFlag } from '$lib/use-below-breakpoint.svelte';

  type SectionDef = EditSectionDef<TKey>;

  let {
    basePath,
    sections,
    defaultSegment,
    editor: editorSnippet,
    immediateEditor,
  }: {
    basePath: string;
    sections: SectionDef[];
    defaultSegment: string;
    editor: Snippet<[TKey, EditorCallbacks]>;
    /**
     * Optional renderer for sections declared with `usesSectionEditorForm: false`
     * (e.g. the media modal). The caller owns the full content and a Done button
     * is appended to return to the detail page.
     */
    immediateEditor?: Snippet;
  } = $props();

  let slug = $derived(page.params.slug);
  let sectionSegment = $derived(page.params.section);
  let section = $derived(
    sectionSegment ? sections.find((s) => s.segment === sectionSegment) : undefined,
  );

  const isMobileFlag = createBelowBreakpointFlag(WIDE_BREAKPOINT, null);
  let isMobile = $derived(isMobileFlag.current);

  $effect(() => {
    if (isMobile === true && !section) {
      goto(resolveHref(`${basePath}/${slug}/edit/${defaultSegment}`), {
        replaceState: true,
      });
    }
  });
</script>

<SectionEditHarness {section} detailHref={`${basePath}/${slug}`} {immediateEditor}>
  {#snippet editor(callbacks, activeSection)}
    {@render editorSnippet(activeSection.key, callbacks)}
  {/snippet}
</SectionEditHarness>
