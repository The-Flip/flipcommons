<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { resolve } from '$app/paths';
  import { formatYearRange } from '$lib/utils';
  import MetaTags from '$lib/components/layout/site/MetaTags.svelte';
  import { metaDescriptionFor } from '$lib/components/layout/site/meta-tags';
  import JsonLd from '$lib/components/layout/site/JsonLd.svelte';
  import { auth } from '$lib/auth.svelte';
  import LocationLink from '$lib/components/LocationLink.svelte';
  import PageActionBar from '$lib/components/layout/page/PageActionBar.svelte';
  import RecordDetailShell from '$lib/components/pages/record/detail/RecordDetailShell.svelte';
  import SectionEditorHost from '$lib/components/pages/record/edit/SectionEditorHost.svelte';
  import SidebarSection from '$lib/components/layout/page/sidebar/SidebarSection.svelte';
  import {
    getMenuItemAction,
    type EditSectionMenuItem,
  } from '$lib/components/layout/page/edit-section-menu';
  import { corporateEntityEditActionContext } from '$lib/components/editors/edit-action-context';
  import {
    findCorporateEntitySectionByKey,
    findCorporateEntitySectionBySegment,
    CORPORATE_ENTITY_EDIT_SECTIONS,
    type CorporateEntityEditSectionKey,
  } from '$lib/components/editors/corporate-entity-edit-sections';
  import { WIDE_BREAKPOINT } from '$lib/constants';
  import { resolveDetailSubrouteMode } from '$lib/detail-subroute-mode';
  import { isFocusModePath } from '$lib/focus-mode';
  import { setEntityContext } from '$lib/entity-context';
  import { createBelowBreakpointFlag } from '$lib/use-below-breakpoint.svelte';
  import CorporateEntityEditorSwitch from './edit/CorporateEntityEditorSwitch.svelte';

  let { data, children } = $props();
  let ce = $derived(data.profile);
  let slug = $derived(page.params.slug);

  let yearsActive = $derived(formatYearRange(ce.year_start, ce.year_end));
  let metaDescription = $derived(metaDescriptionFor(ce));
  let mode = $derived(resolveDetailSubrouteMode(page.url.pathname));
  let isDetail = $derived(mode === 'detail');
  let isFocusMode = $derived(isFocusModePath(page.url.pathname));

  setEntityContext({
    get name() {
      return ce.name;
    },
    get detailHref() {
      return resolve(`/corporate-entities/${slug}`);
    },
  });
  const isMobileFlag = createBelowBreakpointFlag(WIDE_BREAKPOINT);
  let isMobile = $derived(isMobileFlag.current);
  let editing = $state<CorporateEntityEditSectionKey | null>(null);
  let syncEnabled = $derived(!isMobile && !isFocusMode);
  // Tracks the last URL-derived edit section so local modal state doesn't immediately write it back.
  let lastUrlEditing = $state<CorporateEntityEditSectionKey | null>(null);

  $effect(() => {
    auth.load();
  });

  function updateEditQuery(nextEditing: CorporateEntityEditSectionKey | null) {
    const current = page.url.searchParams.get('edit') ?? null;
    const desired = nextEditing
      ? (findCorporateEntitySectionByKey(nextEditing)?.segment ?? null)
      : null;
    if (current === desired) return;
    const url = new URL(page.url);
    if (desired) url.searchParams.set('edit', desired);
    else url.searchParams.delete('edit');
    goto(`${url.pathname}${url.search}`, { replaceState: true, noScroll: true, keepFocus: true });
  }

  function resolveEditingFromUrl(): CorporateEntityEditSectionKey | null {
    if (!syncEnabled) return null;
    const section = page.url.searchParams.get('edit');
    const matched = section ? findCorporateEntitySectionBySegment(section) : undefined;
    return matched?.key ?? null;
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

  // Years active appears as a mobile meta bar (hero metaItems) only; on desktop
  // it's surfaced via the sidebar "Years Active" section, so suppress it here
  // to avoid duplication.
  let metaItems = $derived(isMobile && yearsActive ? [{ text: yearsActive }] : []);
  let parentLink = $derived({
    text: ce.manufacturer.name,
    href: resolve(`/manufacturers/${ce.manufacturer.public_id}`),
  });

  let editSections: EditSectionMenuItem[] = $derived([
    ...CORPORATE_ENTITY_EDIT_SECTIONS.map((section) =>
      isMobile
        ? {
            key: section.key,
            label: section.label,
            href: resolve(`/corporate-entities/${slug}/edit/${section.segment}`),
          }
        : {
            key: section.key,
            label: section.label,
            onclick: () => (editing = section.key),
          },
    ),
    {
      key: 'delete-corporate-entity',
      label: `Delete ${ce.name}`,
      href: resolve(`/corporate-entities/${slug}/delete`),
      separatorBefore: true,
    },
  ]);

  function editAction(sectionKey: CorporateEntityEditSectionKey): (() => void) | undefined {
    if (!auth.isAuthenticated) return undefined;
    return getMenuItemAction(editSections, sectionKey, (href) => goto(href));
  }

  corporateEntityEditActionContext.set(editAction);
</script>

<MetaTags title={ce.name} description={metaDescription} url={page.url.href} />

{#if isDetail && data.jsonLd}
  <JsonLd data={data.jsonLd} />
{/if}

{#if isFocusMode}
  {@render children()}
{:else}
  {#snippet actionBar()}
    <PageActionBar
      detailHref={isDetail ? undefined : resolve(`/corporate-entities/${slug}`)}
      editSections={auth.isAuthenticated ? editSections : undefined}
      historyHref={resolve(`/corporate-entities/${slug}/edit-history`)}
      sourcesHref={resolve(`/corporate-entities/${slug}/sources`)}
    />
  {/snippet}

  {#snippet main()}
    {@render children()}
  {/snippet}

  {#snippet sidebar()}
    <SidebarSection heading="Manufacturer">
      <p class="sidebar-value">
        <a href={resolve(`/manufacturers/${ce.manufacturer.public_id}`)}>{ce.manufacturer.name}</a>
      </p>
    </SidebarSection>

    {#if yearsActive}
      <SidebarSection heading="Years Active" onEdit={editAction('basics')}>
        <p class="sidebar-value">{yearsActive}</p>
      </SidebarSection>
    {/if}

    {#if ce.locations && ce.locations.length > 0}
      <SidebarSection heading="Locations">
        {#each ce.locations as loc, i (i)}
          <LocationLink {loc} />
        {/each}
      </SidebarSection>
    {/if}

    {#if ce.aliases && ce.aliases.length > 0}
      <SidebarSection heading="Also known as" onEdit={editAction('aliases')}>
        <p class="aliases">{ce.aliases.join(', ')}</p>
      </SidebarSection>
    {/if}
  {/snippet}

  <RecordDetailShell
    name={ce.name}
    {parentLink}
    {metaItems}
    sidebarDesktopOnly={isDetail}
    {actionBar}
    {main}
    {sidebar}
  />

  <SectionEditorHost
    bind:editingKey={editing}
    sections={CORPORATE_ENTITY_EDIT_SECTIONS}
    switcherItems={editSections}
  >
    {#snippet editor(key, { ref, onsaved, onerror, ondirtychange })}
      <CorporateEntityEditorSwitch
        sectionKey={key}
        initialData={ce}
        slug={ce.slug}
        bind:editorRef={ref.current}
        {onsaved}
        {onerror}
        {ondirtychange}
      />
    {/snippet}
  </SectionEditorHost>
{/if}

<style>
  .sidebar-value {
    font-size: var(--font-size-1);
    color: var(--color-text);
    margin: 0;
  }

  .sidebar-value a {
    color: var(--color-link);
    text-decoration: none;
  }

  .sidebar-value a:hover {
    text-decoration: underline;
  }

  .aliases {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
    margin: 0;
  }
</style>
