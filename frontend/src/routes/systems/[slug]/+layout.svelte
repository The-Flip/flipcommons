<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { resolve } from '$app/paths';
  import { SITE_NAME } from '$lib/constants';
  import { auth } from '$lib/auth.svelte';
  import MetaTags from '$lib/components/MetaTags.svelte';
  import PageActionBar from '$lib/components/PageActionBar.svelte';
  import RecordDetailShell from '$lib/components/RecordDetailShell.svelte';
  import SectionEditorHost from '$lib/components/SectionEditorHost.svelte';
  import SidebarList from '$lib/components/SidebarList.svelte';
  import SidebarListItem from '$lib/components/SidebarListItem.svelte';
  import SidebarSection from '$lib/components/SidebarSection.svelte';
  import { type EditSectionMenuItem } from '$lib/components/edit-section-menu';
  import {
    findSystemSectionByKey,
    findSystemSectionBySegment,
    SYSTEM_EDIT_SECTIONS,
    type SystemEditSectionKey,
  } from '$lib/components/editors/system-edit-sections';
  import { WIDE_BREAKPOINT } from '$lib/constants';
  import { resolveDetailSubrouteMode } from '$lib/detail-subroute-mode';
  import { isFocusModePath } from '$lib/focus-mode';
  import { setEntityContext } from '$lib/entity-context';
  import { createBelowBreakpointFlag } from '$lib/use-below-breakpoint.svelte';
  import SystemEditorSwitch from './edit/SystemEditorSwitch.svelte';

  let { data, children } = $props();
  let system = $derived(data.system);
  let slug = $derived(page.params.slug);

  let metaDescription = $derived(system.description?.text || `${system.name} — ${SITE_NAME}`);
  let mode = $derived(resolveDetailSubrouteMode(page.url.pathname));
  let isDetail = $derived(mode === 'detail');
  let isFocusMode = $derived(isFocusModePath(page.url.pathname));

  setEntityContext({
    get name() {
      return system.name;
    },
    get detailHref() {
      return resolve(`/systems/${slug}`);
    },
  });
  const isMobileFlag = createBelowBreakpointFlag(WIDE_BREAKPOINT);
  let isMobile = $derived(isMobileFlag.current);
  let editing = $state<SystemEditSectionKey | null>(null);
  let syncEnabled = $derived(!isMobile && !isFocusMode);
  let lastUrlEditing = $state<SystemEditSectionKey | null>(null);

  $effect(() => {
    auth.load();
  });

  function updateEditQuery(nextEditing: SystemEditSectionKey | null) {
    const current = page.url.searchParams.get('edit') ?? null;
    const desired = nextEditing ? (findSystemSectionByKey(nextEditing)?.segment ?? null) : null;
    if (current === desired) return;
    const url = new URL(page.url);
    if (desired) url.searchParams.set('edit', desired);
    else url.searchParams.delete('edit');
    goto(`${url.pathname}${url.search}`, { replaceState: true, noScroll: true, keepFocus: true });
  }

  function resolveEditingFromUrl(): SystemEditSectionKey | null {
    if (!syncEnabled) return null;
    const section = page.url.searchParams.get('edit');
    const matched = section ? findSystemSectionBySegment(section) : undefined;
    return matched?.key ?? null;
  }

  // URL → state. Must assign `editing` unconditionally. An `if (editing !==
  // nextEditing)` guard turns `editing` into a read-dep of this effect,
  // which re-runs on local writes and reverts the user's click in the same
  // tick. Same-value $state writes are already no-ops.
  $effect(() => {
    const nextEditing = resolveEditingFromUrl();
    lastUrlEditing = nextEditing;
    editing = nextEditing;
  });

  $effect(() => {
    if (!syncEnabled) return;
    if (editing === lastUrlEditing) return;
    lastUrlEditing = editing;
    updateEditQuery(editing);
  });

  let editSections: EditSectionMenuItem[] = $derived([
    ...SYSTEM_EDIT_SECTIONS.map((section) =>
      isMobile
        ? {
            key: section.key,
            label: section.label,
            href: resolve(`/systems/${slug}/edit/${section.segment}`),
          }
        : {
            key: section.key,
            label: section.label,
            onclick: () => (editing = section.key),
          },
    ),
    {
      key: 'delete',
      label: 'Delete System',
      href: resolve(`/systems/${slug}/delete`),
      separatorBefore: true,
    },
  ]);
</script>

<MetaTags title={system.name} description={metaDescription} url={page.url.href} />

{#if isFocusMode}
  {@render children()}
{:else}
  {#snippet actionBar()}
    <PageActionBar
      detailHref={isDetail ? undefined : resolve(`/systems/${slug}`)}
      editSections={auth.isAuthenticated ? editSections : undefined}
      historyHref={resolve(`/systems/${slug}/edit-history`)}
      sourcesHref={resolve(`/systems/${slug}/sources`)}
    />
  {/snippet}

  {#snippet main()}
    {@render children()}
  {/snippet}

  {#snippet sidebar()}
    {#if system.manufacturer}
      <SidebarSection heading="Manufacturer">
        <a href={resolve(`/manufacturers/${system.manufacturer.public_id}`)}
          >{system.manufacturer.name}</a
        >
      </SidebarSection>
    {/if}

    {#if system.sibling_systems.length > 0}
      <SidebarSection heading="Other Systems By This Manufacturer">
        <SidebarList>
          {#each system.sibling_systems as sibling (sibling.public_id)}
            <SidebarListItem>
              <a href={resolve(`/systems/${sibling.public_id}`)}>{sibling.name}</a>
            </SidebarListItem>
          {/each}
        </SidebarList>
      </SidebarSection>
    {/if}
  {/snippet}

  <RecordDetailShell
    name={system.name}
    parentLink={{ text: 'Systems', href: resolve('/systems') }}
    {actionBar}
    {main}
    {sidebar}
    sidebarDesktopOnly={true}
  />

  <SectionEditorHost
    bind:editingKey={editing}
    sections={SYSTEM_EDIT_SECTIONS.map((section) => ({
      ...section,
      usesSectionEditorForm: true,
    }))}
    switcherItems={editSections}
  >
    {#snippet editor(key, { ref, onsaved, onerror, ondirtychange })}
      <SystemEditorSwitch
        sectionKey={key}
        initialData={system}
        slug={system.slug}
        bind:editorRef={ref.current}
        {onsaved}
        {onerror}
        {ondirtychange}
      />
    {/snippet}
  </SectionEditorHost>
{/if}
