<script lang="ts">
  import ActionMenu from './ActionMenu.svelte';
  import MenuItem from './MenuItem.svelte';
</script>

<ActionMenu label="Account" variant="bare">
  {#snippet trigger()}
    <span data-testid="custom-trigger">AB</span>
  {/snippet}
  <MenuItem href="/profile">Profile</MenuItem>
  <MenuItem href="/logout">Sign Out</MenuItem>
</ActionMenu>
