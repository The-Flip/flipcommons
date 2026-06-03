<script lang="ts">
  import ActionMenu from './ActionMenu.svelte';
  import MenuItem from './MenuItem.svelte';
</script>

<div data-testid="clip-wrapper" class="clip-wrapper">
  <ActionMenu label="Tools">
    <MenuItem href="/a">A</MenuItem>
    <MenuItem href="/b">B</MenuItem>
  </ActionMenu>
</div>

<style>
  .clip-wrapper {
    overflow: hidden;
    width: 40px;
    height: 40px;
  }
</style>
