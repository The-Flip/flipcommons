<script lang="ts">
  import { resolve } from '$app/paths';

  let { data } = $props();
  let mfr = $derived(data.manufacturer);
</script>

<section class="systems">
  {#if mfr.systems.length === 0}
    <p class="empty">No systems for this manufacturer.</p>
  {:else}
    <ul>
      {#each mfr.systems as system (system.public_id)}
        <li>
          <a href={resolve(`/systems/${system.public_id}`)}>{system.name}</a>
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  ul {
    list-style: none;
    padding: 0;
  }

  li {
    padding: var(--size-3) 0;
    border-bottom: 1px solid var(--color-border-soft);
    font-size: var(--font-size-2);
  }

  .empty {
    color: var(--color-text-muted);
    font-size: var(--font-size-2);
    padding: var(--size-8) 0;
    text-align: center;
  }
</style>
