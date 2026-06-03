<script lang="ts">
  import FilterDrawer from './FilterDrawer.svelte';
</script>

{#snippet children()}
  <div>Drawer content</div>
{/snippet}

<FilterDrawer label="Filter manufacturers" {children} />
