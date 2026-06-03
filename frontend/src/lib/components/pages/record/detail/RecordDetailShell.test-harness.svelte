<script lang="ts">
  import RecordDetailShell from './RecordDetailShell.svelte';

  let {
    showActionBar = true,
    showSidebar = true,
    sidebarDesktopOnly = false,
  }: {
    showActionBar?: boolean;
    showSidebar?: boolean;
    sidebarDesktopOnly?: boolean;
  } = $props();
</script>

{#snippet actionBarSnippet()}
  <nav aria-label="Page actions">Actions</nav>
{/snippet}

{#snippet mainSnippet()}
  <div>Main content</div>
{/snippet}

{#snippet sidebarSnippet()}
  <div>Sidebar content</div>
{/snippet}

<RecordDetailShell
  name="Medieval Madness"
  heroImageUrl="https://example.com/hero.jpg"
  heroImageAlt="Backglass"
  parentLink={{ text: 'Titles', href: '/titles/medieval-madness' }}
  metaItems={[{ text: 'Williams', href: '/manufacturers/williams' }, { text: '1997' }]}
  {sidebarDesktopOnly}
  actionBar={showActionBar ? actionBarSnippet : undefined}
  main={mainSnippet}
  sidebar={showSidebar ? sidebarSnippet : undefined}
/>
