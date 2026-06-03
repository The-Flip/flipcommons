<script lang="ts">
  import List from './List.svelte';
  import ListItem from './ListItem.svelte';

  let { withActions = false, href }: { withActions?: boolean; href?: string } = $props();
</script>

{#snippet editAction()}
  <button data-testid="row-action">Edit</button>
{/snippet}

<List>
  <ListItem {href} actions={withActions ? editAction : undefined}>
    <span data-testid="row-content">First row</span>
  </ListItem>
  <ListItem>
    <span>Second row</span>
  </ListItem>
</List>
