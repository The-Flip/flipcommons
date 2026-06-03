<script lang="ts">
  import TitleFilterSidebar from './TitleFilterSidebar.svelte';
  import { emptyFilterState } from '$lib/facet-engine';

  // Cold-load state: options still streaming, so `filterOptions` is undefined. Exercises
  // every guarded derivation — including `playerCountChipOptions`, which builds its own
  // buckets rather than going through `toOptions` and so needs its own undefined guard.
  let filters = $state(emptyFilterState());
</script>

<TitleFilterSidebar filterOptions={undefined} disabled bind:filters />
