<script lang="ts">
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import { page } from '$app/state';
  import { auth } from '$lib/auth.svelte';
  import { WIDE_BREAKPOINT, pageTitle } from '$lib/constants';
  import PageActionBar from '$lib/components/layout/page/PageActionBar.svelte';
  import RecordDetailShell from '$lib/components/RecordDetailShell.svelte';
  import SectionEditorHost from '$lib/components/SectionEditorHost.svelte';
  import SidebarList from '$lib/components/layout/page/sidebar/SidebarList.svelte';
  import SidebarListItem from '$lib/components/layout/page/sidebar/SidebarListItem.svelte';
  import SidebarSection from '$lib/components/layout/page/sidebar/SidebarSection.svelte';
  import type { Crumb } from '$lib/components/layout/page/Breadcrumb.svelte';
  import { getMenuItemAction, type EditSectionMenuItem } from '$lib/components/edit-section-menu';
  import { locationEditActionContext } from '$lib/components/editors/edit-action-context';
  import {
    findLocationSectionByKey,
    findLocationSectionBySegment,
    locationEditSectionsFor,
    type LocationEditSectionDef,
    type LocationEditSectionKey,
  } from '$lib/components/editors/location-edit-sections';
  import { createBelowBreakpointFlag } from '$lib/use-below-breakpoint.svelte';
  import { childrenHeading, newChildLabel, type LocationDetail } from './location-helpers';
  import LocationEditorSwitch from './edit/LocationEditorSwitch.svelte';

  let { data, children } = $props();

  let profile = $derived<LocationDetail>(data.profile);
  let isRoot = $derived(profile.location_type === null);
  let path = $derived(profile.public_id);
  let displayName = $derived(profile.name || 'Locations');

  let breadcrumbs = $derived<Crumb[] | null>(
    isRoot
      ? null
      : [
          { label: 'Locations', href: '/locations' },
          ...profile.ancestors.map((a) => ({
            label: a.name,
            href: `/locations/${a.public_id}`,
          })),
        ],
  );

  const isMobileFlag = createBelowBreakpointFlag(WIDE_BREAKPOINT);
  let isMobile = $derived(isMobileFlag.current);
  let editing = $state<LocationEditSectionKey | null>(null);
  let visibleSections = $derived<LocationEditSectionDef[]>(
    locationEditSectionsFor(profile.location_type),
  );
  let syncEnabled = $derived(!isMobile);
  let lastUrlEditing = $state<LocationEditSectionKey | null>(null);

  function updateEditQuery(nextEditing: LocationEditSectionKey | null) {
    const current = page.url.searchParams.get('edit') ?? null;
    const desired = nextEditing ? (findLocationSectionByKey(nextEditing)?.segment ?? null) : null;
    if (current === desired) return;
    const url = new URL(page.url);
    if (desired) url.searchParams.set('edit', desired);
    else url.searchParams.delete('edit');
    goto(`${url.pathname}${url.search}`, { replaceState: true, noScroll: true, keepFocus: true });
  }

  function resolveEditingFromUrl(): LocationEditSectionKey | null {
    if (!syncEnabled) return null;
    const segment = page.url.searchParams.get('edit');
    const matched = segment ? findLocationSectionBySegment(segment) : undefined;
    if (!matched) return null;
    if (matched.countryOnly && profile.location_type !== 'country') return null;
    return matched.key;
  }

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

  let editMenuItems = $derived.by<EditSectionMenuItem[]>(() => {
    if (isRoot) {
      return [{ key: 'new', label: '+ New Country', href: resolve('/locations/new') }];
    }
    const childLabel = newChildLabel(profile);
    // Name, parent, slug, and location_type are intentionally absent because
    // they define the location's canonical path and hierarchy.
    const items: EditSectionMenuItem[] = visibleSections.map((section) =>
      isMobile
        ? {
            key: section.key,
            label: section.label,
            href: resolve(`/locations/${path}/edit/${section.segment}`),
          }
        : {
            key: section.key,
            label: section.label,
            onclick: () => (editing = section.key),
          },
    );
    if (childLabel) {
      items.push({
        key: 'new',
        label: `+ New ${childLabel}`,
        href: resolve(`/locations/${path}/new`),
      });
    }
    items.push({
      key: 'delete',
      label: `Delete ${profile.name}`,
      href: resolve(`/locations/${path}/delete`),
      separatorBefore: true,
    });
    return items;
  });

  $effect(() => {
    void auth.load();
  });

  function editAction(sectionKey: LocationEditSectionKey): (() => void) | undefined {
    if (!auth.isAuthenticated) return undefined;
    return getMenuItemAction(editMenuItems, sectionKey, (href) => goto(href));
  }

  locationEditActionContext.set(editAction);
</script>

<svelte:head>
  <title>{pageTitle(displayName)}</title>
</svelte:head>

{#snippet actionBar()}
  {#if isRoot}
    {#if auth.isAuthenticated}
      <PageActionBar editSections={editMenuItems} />
    {/if}
  {:else}
    <PageActionBar
      editSections={auth.isAuthenticated ? editMenuItems : undefined}
      historyHref={resolve(`/locations/${path}/edit-history`)}
      sourcesHref={resolve(`/locations/${path}/sources`)}
    />
  {/if}
{/snippet}

{#snippet sidebar()}
  {#if profile.children.length > 0}
    <SidebarSection heading={childrenHeading(profile.children)}>
      <SidebarList>
        {#each profile.children as child (child.public_id)}
          <SidebarListItem>
            <a href={resolve(`/locations/${child.public_id}`)}>
              {child.name}
            </a>
            <span class="count">{child.manufacturer_count}</span>
          </SidebarListItem>
        {/each}
      </SidebarList>
    </SidebarSection>
  {/if}
{/snippet}

<RecordDetailShell name={displayName} {breadcrumbs} {actionBar} {sidebar}>
  {#snippet main()}
    {@render children()}
  {/snippet}
</RecordDetailShell>

{#if !isRoot}
  <SectionEditorHost
    bind:editingKey={editing}
    sections={visibleSections}
    switcherItems={editMenuItems}
  >
    {#snippet editor(key, { ref, onsaved, onerror, ondirtychange })}
      <LocationEditorSwitch
        sectionKey={key}
        initialData={profile}
        publicId={profile.public_id}
        bind:editorRef={ref.current}
        {onsaved}
        {onerror}
        {ondirtychange}
      />
    {/snippet}
  </SectionEditorHost>
{/if}

<style>
  .count {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
  }
</style>
