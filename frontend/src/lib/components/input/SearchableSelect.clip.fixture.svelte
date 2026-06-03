<script lang="ts">
  import SearchableSelect from './SearchableSelect.svelte';

  const options = [
    { value: 'stern', label: 'Stern Pinball', count: 5 },
    { value: 'bally', label: 'Bally', count: 3 },
  ];
</script>

<div data-testid="clip-wrapper" class="clip-wrapper">
  <SearchableSelect {options} label="Manufacturer" placeholder="Search..." selected={null} />
</div>

<style>
  .clip-wrapper {
    overflow: hidden;
    width: 200px;
    height: 40px;
  }
</style>
