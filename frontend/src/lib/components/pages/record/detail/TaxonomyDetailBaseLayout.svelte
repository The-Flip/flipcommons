<script lang="ts" generics="TKey extends string">
  import { untrack, type Snippet } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { resolveHref } from '$lib/utils';
  import { WIDE_BREAKPOINT } from '$lib/constants';
  import { auth } from '$lib/auth.svelte';
  import MetaTags from '$lib/components/layout/site/MetaTags.svelte';
  import JsonLd from '$lib/components/layout/site/JsonLd.svelte';
  import { metaDescriptionFor } from '$lib/components/layout/site/meta-tags';
  import PageActionBar from '$lib/components/layout/page/PageActionBar.svelte';
  import RecordDetailShell from './RecordDetailShell.svelte';
  import type { Crumb } from '$lib/components/layout/page/Breadcrumb.svelte';
  import SectionEditorHost from '$lib/components/pages/record/edit/SectionEditorHost.svelte';
  import {
    getMenuItemAction,
    type EditSectionMenuItem,
  } from '$lib/components/layout/page/edit-section-menu';
  import type { EditSectionDef } from '$lib/components/pages/record/edit/editors/edit-section-def';
  import type {
    EditActionContext,
    EditActionFn,
  } from '$lib/components/pages/record/edit/editors/edit-action-context';
  import type { SectionEditorHandle } from '$lib/components/pages/record/edit/editors/editor-contract';
  import { resolveDetailSubrouteMode } from '$lib/detail-subroute-mode';
  import { isFocusModePath } from '$lib/focus-mode';
  import { setEntityContext } from '$lib/entity-context';
  import { createBelowBreakpointFlag } from '$lib/use-below-breakpoint.svelte';

  type SectionDef = EditSectionDef<TKey> & { usesSectionEditorForm: boolean };

  type EditorRefBox = { current: SectionEditorHandle | undefined };
  type EditorCallbacks = {
    ref: EditorRefBox;
    onsaved: () => void;
    onerror: (msg: string) => void;
    ondirtychange: (dirty: boolean) => void;
  };

  let {
    profile,
    jsonLd,
    parentLabel,
    basePath,
    parentHref,
    breadcrumbs,
    sections,
    editor: editorSnippet,
    immediateEditor,
    sidebar,
    aliases = [],
    editActionContext,
    deleteHref,
    createChild,
    children,
  }: {
    profile: { name: string; slug: string; description: { plain: string } };
    /** JSON-LD `@graph` for this entity's detail page. Rendered only on the
     * detail route (not edit-history/sources sub-routes). */
    jsonLd?: Record<string, unknown>;
    parentLabel: string;
    /** Used to construct this entity's own sub-route URLs (edit, sources, etc.). */
    basePath: string;
    /**
     * Optional override for the parent-link href shown in the page header.
     * Defaults to `basePath`. Use this when the entity's list page lives at
     * a different URL than its detail routes — e.g. display subtypes are
     * listed under `/display-types` but their detail routes remain under
     * `/display-subtypes/`.
     */
    parentHref?: string;
    /**
     * Optional multi-level trail shown in place of the single `parentLabel`
     * kicker — for entities nested under a parent (e.g. a display subtype under
     * its display type). The current entity's name is appended automatically.
     */
    breadcrumbs?: Crumb[];
    sections: SectionDef[];
    editor: Snippet<[TKey, EditorCallbacks]>;
    immediateEditor?: Snippet;
    sidebar?: Snippet;
    aliases?: string[];
    /**
     * Optional context to publish an `editAction(sectionKey)` function the
     * detail `+page.svelte` can use for accordion `[edit]` affordances.
     * On desktop, the action opens the SectionEditorHost modal; on mobile,
     * it navigates to the mobile section route. Auth-gated.
     */
    editActionContext?: EditActionContext<TKey>;
    /** When set, appends a "Delete X" trailing item to the Edit menu. */
    deleteHref?: string;
    /** When set, appends a "New {label}" trailing item to the Edit menu (parent entities only). */
    createChild?: { href: string; label: string };
    children: Snippet;
  } = $props();

  let slug = $derived(page.params.slug);

  let metaDescription = $derived(metaDescriptionFor(profile));
  let mode = $derived(resolveDetailSubrouteMode(page.url.pathname));
  let isDetail = $derived(mode === 'detail');
  let isFocusMode = $derived(isFocusModePath(page.url.pathname));
  const isMobileFlag = createBelowBreakpointFlag(WIDE_BREAKPOINT);
  let isMobile = $derived(isMobileFlag.current);
  let editing = $state<TKey | null>(null);
  let syncEnabled = $derived(!isMobile && !isFocusMode);
  let lastUrlEditing = $state<TKey | null>(null);

  setEntityContext({
    get name() {
      return profile.name;
    },
    get detailHref() {
      return resolveHref(`${basePath}/${slug}`);
    },
  });

  $effect(() => {
    auth.load();
  });

  function updateEditQuery(nextEditing: TKey | null) {
    const current = page.url.searchParams.get('edit') ?? null;
    const desired = nextEditing
      ? (sections.find((s) => s.key === nextEditing)?.segment ?? null)
      : null;
    if (current === desired) return;
    const url = new URL(page.url);
    if (desired) url.searchParams.set('edit', desired);
    else url.searchParams.delete('edit');
    goto(`${url.pathname}${url.search}`, { replaceState: true, noScroll: true, keepFocus: true });
  }

  function resolveEditingFromUrl(): TKey | null {
    if (!syncEnabled) return null;
    const segment = page.url.searchParams.get('edit');
    const matched = segment ? sections.find((s) => s.segment === segment) : undefined;
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
    ...sections.map(
      (section): EditSectionMenuItem =>
        isMobile
          ? {
              key: section.key,
              label: section.label,
              href: resolveHref(`${basePath}/${slug}/edit/${section.segment}`),
            }
          : {
              key: section.key,
              label: section.label,
              onclick: () => (editing = section.key),
            },
    ),
    // Trailing items — always hrefs, mode-agnostic. Create-child before
    // Delete so the destructive action is last.
    ...(createChild
      ? [
          {
            key: 'create-child',
            label: `New ${createChild.label}`,
            href: resolveHref(createChild.href),
          } as EditSectionMenuItem,
        ]
      : []),
    ...(deleteHref
      ? [
          {
            key: 'delete',
            label: `Delete ${profile.name}`,
            href: resolveHref(deleteHref),
            separatorBefore: true,
          } as EditSectionMenuItem,
        ]
      : []),
  ]);

  const editAction: EditActionFn<TKey> = (key) => {
    if (!auth.isAuthenticated) return undefined;
    return getMenuItemAction(editSections, key, (href) => goto(href));
  };

  // setContext must run during initialization (not in $effect) for descendants
  // to see it. The prop's reference is stable for the layout's lifetime, so
  // `untrack` is correct here — we don't want a reactivity dependency.
  untrack(() => {
    if (editActionContext) editActionContext.set(editAction);
  });
</script>

<MetaTags title={profile.name} description={metaDescription} url={page.url.href} />

{#if isDetail && jsonLd}
  <JsonLd data={jsonLd} />
{/if}

{#if isFocusMode}
  {@render children()}
{:else}
  {#snippet actionBar()}
    <PageActionBar
      detailHref={isDetail ? undefined : resolveHref(`${basePath}/${slug}`)}
      editSections={auth.isAuthenticated ? editSections : undefined}
      historyHref={resolveHref(`${basePath}/${slug}/edit-history`)}
      sourcesHref={resolveHref(`${basePath}/${slug}/sources`)}
    />
  {/snippet}

  {#snippet main()}
    {@render children()}
  {/snippet}

  <RecordDetailShell
    name={profile.name}
    parentLink={breadcrumbs
      ? null
      : { text: parentLabel, href: resolveHref(parentHref ?? basePath) }}
    {breadcrumbs}
    {aliases}
    {actionBar}
    {main}
    {sidebar}
    sidebarDesktopOnly={isDetail}
  />

  <SectionEditorHost
    bind:editingKey={editing}
    {sections}
    switcherItems={editSections}
    editor={editorSnippet}
    {immediateEditor}
  />
{/if}
