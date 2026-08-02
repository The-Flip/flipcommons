<script lang="ts">
  import GameFilterSidebar from './GameFilterSidebar.svelte';
  import { emptyFilterState } from '$lib/filters/games';

  // Cold-load state: options still streaming, so `filterOptions` is undefined. Exercises
  // every guarded derivation — including `playerCountChipOptions`, which builds its own
  // buckets rather than going through `toOptions` and so needs its own undefined guard.
  let filters = $state(emptyFilterState());
</script>

<GameFilterSidebar filterOptions={undefined} disabled bind:filters />
