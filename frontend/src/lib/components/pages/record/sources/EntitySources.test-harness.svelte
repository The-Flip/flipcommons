<script lang="ts">
  import EntitySources from './EntitySources.svelte';
  import { setEntityContext } from '$lib/entity-context';

  let { sources } = $props();

  setEntityContext({
    name: 'Test Entity',
    detailHref: '/test-entity/test-slug',
  });
</script>

<EntitySources {sources} />
