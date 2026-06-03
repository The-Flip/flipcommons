<script lang="ts">
  import { page } from '$app/state';
  import { resolve } from '$app/paths';
  import { auth } from '$lib/auth.svelte';
  import { modelHasTitleOwnedIdentity } from '$lib/catalog-rules';
  import EditSectionShell from '$lib/components/pages/record/edit/EditSectionShell.svelte';
  import type { EditSectionMenuItem } from '$lib/components/layout/page/edit-section-menu';
  import { setEditLayoutContext } from '$lib/components/pages/record/edit/editors/edit-layout-context';
  import {
    findSectionBySegment,
    modelSectionsFor,
  } from '$lib/components/pages/record/edit/editors/entity/model/model-edit-sections';

  let { children, data } = $props();
  let slug = $derived(page.params.slug);
  let sectionSegment = $derived(page.params.section);
  let currentSection = $derived(sectionSegment ? findSectionBySegment(sectionSegment) : undefined);
  let availableSections = $derived(modelSectionsFor(modelHasTitleOwnedIdentity(data.profile)));

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
      href: resolve(`/models/${slug}/edit/${s.segment}`),
    })),
  );
</script>

<EditSectionShell
  detailHref={resolve(`/models/${slug}`)}
  {switcherItems}
  currentSectionKey={currentSection?.key}
  {editorDirty}
>
  {@render children()}
</EditSectionShell>
