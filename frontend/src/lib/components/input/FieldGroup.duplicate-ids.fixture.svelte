<script lang="ts">
  import NumberField from './NumberField.svelte';

  let first = $state('');
  let second = $state('');
</script>

<NumberField label="Year" bind:value={first} />
<NumberField label="Year" bind:value={second} />
