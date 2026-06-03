<script lang="ts" generics="TKey extends string">
  import type { Snippet } from 'svelte';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { resolveHref } from '$lib/utils';
  import EditSectionShell from './EditSectionShell.svelte';
  import type { EditSectionMenuItem } from '$lib/components/layout/page/edit-section-menu';
  import type { EditSectionDef } from '$lib/components/editors/edit-section-def';
  import { setEditLayoutContext } from '$lib/components/editors/edit-layout-context';
  import { WIDE_BREAKPOINT } from '$lib/constants';
  import { createBelowBreakpointFlag } from '$lib/use-below-breakpoint.svelte';

  let {
    basePath,
    sections,
    defaultSegment,
    children,
  }: {
    basePath: string;
    sections: EditSectionDef<TKey>[];
    defaultSegment: string;
    children: Snippet;
  } = $props();

  let slug = $derived(page.params.slug);
  let sectionSegment = $derived(page.params.section);
  let currentSection = $derived(
    sectionSegment ? sections.find((s) => s.segment === sectionSegment) : undefined,
  );
  let editorDirty = $state(false);
  const isMobileFlag = createBelowBreakpointFlag(WIDE_BREAKPOINT, null);
  let isMobile = $derived(isMobileFlag.current);

  setEditLayoutContext({
    setDirty(dirty: boolean) {
      editorDirty = dirty;
    },
  });

  let switcherItems: EditSectionMenuItem[] = $derived(
    sections.map((section) => ({
      key: section.key,
      label: section.label,
      href: resolveHref(`${basePath}/${slug}/edit/${section.segment}`),
    })),
  );

  $effect(() => {
    if (isMobile !== false) return;
    const segment = currentSection?.segment ?? defaultSegment;
    goto(resolveHref(`${basePath}/${slug}?edit=${segment}`), { replaceState: true });
  });
</script>

{#if isMobile === true}
  <EditSectionShell
    detailHref={resolveHref(`${basePath}/${slug}`)}
    {switcherItems}
    currentSectionKey={currentSection?.key}
    {editorDirty}
  >
    {@render children()}
  </EditSectionShell>
{/if}
