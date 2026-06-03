<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { resolve } from '$app/paths';
  import { auth } from '$lib/auth.svelte';
  import MediaEditor from '$lib/components/pages/record/edit/editors/MediaEditor.svelte';
  import MetaTags from '$lib/components/layout/site/MetaTags.svelte';
  import { metaDescriptionFor } from '$lib/components/layout/site/meta-tags';
  import JsonLd from '$lib/components/layout/site/JsonLd.svelte';
  import PageActionBar from '$lib/components/layout/page/PageActionBar.svelte';
  import RecordDetailShell from '$lib/components/pages/record/detail/RecordDetailShell.svelte';
  import SectionEditorHost from '$lib/components/pages/record/edit/SectionEditorHost.svelte';
  import {
    getMenuItemAction,
    type EditSectionMenuItem,
  } from '$lib/components/layout/page/edit-section-menu';
  import { personEditActionContext } from '$lib/components/pages/record/edit/editors/edit-action-context';
  import {
    findPersonSectionByKey,
    findPersonSectionBySegment,
    PERSON_EDIT_SECTIONS,
    type PersonEditSectionKey,
  } from '$lib/components/pages/record/edit/editors/entity/person/person-edit-sections';
  import { WIDE_BREAKPOINT } from '$lib/constants';
  import { resolveDetailSubrouteMode } from '$lib/detail-subroute-mode';
  import { isFocusModePath } from '$lib/focus-mode';
  import { setEntityContext } from '$lib/entity-context';
  import { createBelowBreakpointFlag } from '$lib/use-below-breakpoint.svelte';
  import PersonEditorSwitch from './edit/PersonEditorSwitch.svelte';

  let { data, children } = $props();
  let person = $derived(data.profile);
  let slug = $derived(page.params.slug);

  let metaDescription = $derived(
    metaDescriptionFor(person, `${person.name} — pinball industry professional`),
  );
  let mode = $derived(resolveDetailSubrouteMode(page.url.pathname));
  let isDetail = $derived(mode === 'detail');
  let isFocusMode = $derived(isFocusModePath(page.url.pathname));

  setEntityContext({
    get name() {
      return person.name;
    },
    get detailHref() {
      return resolve(`/people/${slug}`);
    },
  });
  const isMobileFlag = createBelowBreakpointFlag(WIDE_BREAKPOINT);
  let isMobile = $derived(isMobileFlag.current);
  let editing = $state<PersonEditSectionKey | null>(null);
  let syncEnabled = $derived(!isMobile && !isFocusMode);
  // Tracks the last URL-derived edit section so local modal state doesn't immediately write it back.
  let lastUrlEditing = $state<PersonEditSectionKey | null>(null);

  $effect(() => {
    auth.load();
  });

  function updateEditQuery(nextEditing: PersonEditSectionKey | null) {
    const current = page.url.searchParams.get('edit') ?? null;
    const desired = nextEditing ? (findPersonSectionByKey(nextEditing)?.segment ?? null) : null;
    if (current === desired) return;
    const url = new URL(page.url);
    if (desired) url.searchParams.set('edit', desired);
    else url.searchParams.delete('edit');
    goto(`${url.pathname}${url.search}`, { replaceState: true, noScroll: true, keepFocus: true });
  }

  function resolveEditingFromUrl(): PersonEditSectionKey | null {
    if (!syncEnabled) return null;
    const section = page.url.searchParams.get('edit');
    const matched = section ? findPersonSectionBySegment(section) : undefined;
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

  let editSections: EditSectionMenuItem[] = $derived([
    ...PERSON_EDIT_SECTIONS.map(
      (section): EditSectionMenuItem =>
        isMobile
          ? {
              key: section.key,
              label: section.label,
              href: resolve(`/people/${slug}/edit/${section.segment}`),
            }
          : {
              key: section.key,
              label: section.label,
              onclick: () => (editing = section.key),
            },
    ),
    // "Delete Person" is the last item in the menu (destructive action).
    // Navigates to a focus-mode confirmation page; auth gating rides on
    // PageActionBar's editSections prop, which is only passed when the
    // viewer is authenticated.
    {
      key: 'delete-person',
      label: 'Delete Person',
      href: resolve(`/people/${slug}/delete`),
      separatorBefore: true,
    },
  ]);

  function editAction(sectionKey: PersonEditSectionKey): (() => void) | undefined {
    if (!auth.isAuthenticated) return undefined;
    return getMenuItemAction(editSections, sectionKey, (href) => goto(href));
  }

  personEditActionContext.set(editAction);
</script>

<MetaTags
  title={person.name}
  description={metaDescription}
  url={page.url.href}
  image={person.photo_url}
  imageAlt={person.photo_url ? `Photo of ${person.name}` : undefined}
  ogType="profile"
/>

{#if isDetail && data.jsonLd}
  <JsonLd data={data.jsonLd} />
{/if}

{#if isFocusMode}
  {@render children()}
{:else}
  {#snippet actionBar()}
    <PageActionBar
      detailHref={isDetail ? undefined : resolve(`/people/${slug}`)}
      editSections={auth.isAuthenticated ? editSections : undefined}
      historyHref={resolve(`/people/${slug}/edit-history`)}
      sourcesHref={resolve(`/people/${slug}/sources`)}
    />
  {/snippet}

  {#snippet main()}
    {@render children()}
  {/snippet}

  <RecordDetailShell
    name={person.name}
    parentLink={{ text: 'People', href: resolve('/people') }}
    {actionBar}
    {main}
  />

  <SectionEditorHost
    bind:editingKey={editing}
    sections={PERSON_EDIT_SECTIONS}
    switcherItems={editSections}
  >
    {#snippet editor(key, { ref, onsaved, onerror, ondirtychange })}
      <PersonEditorSwitch
        sectionKey={key}
        initialData={person}
        slug={person.slug}
        bind:editorRef={ref.current}
        {onsaved}
        {onerror}
        {ondirtychange}
      />
    {/snippet}

    {#snippet immediateEditor()}
      <MediaEditor entityType="person" slug={person.slug} media={person.uploaded_media} />
    {/snippet}
  </SectionEditorHost>
{/if}
