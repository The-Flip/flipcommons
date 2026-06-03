<script lang="ts">
  import EditSectionMenu from './EditSectionMenu.svelte';
</script>

<EditSectionMenu
  items={[
    { key: 'overview', label: 'Overview', href: '/models/medieval-madness/edit/overview' },
    {
      key: 'technology',
      label: 'Technology',
      href: '/models/medieval-madness/edit/technology',
    },
    {
      key: 'related-models',
      label: 'Related Models',
      href: '/models/medieval-madness/edit/related-models',
    },
  ]}
/>
