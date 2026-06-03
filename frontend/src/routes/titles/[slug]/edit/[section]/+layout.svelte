<script lang="ts">
  import { page } from '$app/state';
  import { resolve } from '$app/paths';
  import { auth } from '$lib/auth.svelte';
  import EditSectionShell from '$lib/components/pages/record/edit/EditSectionShell.svelte';
  import type { EditSectionMenuItem } from '$lib/components/layout/page/edit-section-menu';
  import { setEditLayoutContext } from '$lib/components/pages/record/edit/editors/edit-layout-context';
  import {
    findTitleSectionBySegment,
    titleSectionsFor,
  } from '$lib/components/pages/record/edit/editors/entity/title/title-edit-sections';

  let { children, data } = $props();
  let slug = $derived(page.params.slug);
  let sectionSegment = $derived(page.params.section);
  let currentSection = $derived(
    sectionSegment ? findTitleSectionBySegment(sectionSegment) : undefined,
  );
  let isSingleModel = $derived(!!data.profile.model_detail);
  let availableSections = $derived(titleSectionsFor(isSingleModel));

  $effect(() => {
    auth.load();
  });

  let editorDirty = $state(false);

  setEditLayoutContext({
    setDirty(dirty: boolean) {
      editorDirty = dirty;
    },
  });

  let switcherItems: EditSectionMenuItem[] = $derived(
    availableSections.map((s) => ({
      key: s.key,
      label: s.label,
      href: resolve(`/titles/${slug}/edit/${s.segment}`),
    })),
  );
</script>

<EditSectionShell
  detailHref={resolve(`/titles/${slug}`)}
  {switcherItems}
  currentSectionKey={currentSection?.key}
  {editorDirty}
>
  {@render children()}
</EditSectionShell>
