<!-- @component Member-level old/new rendering for object-valued claim changes. -->
<script lang="ts">
  import type { StructuredDiffPart } from './change-display';

  let { parts }: { parts: StructuredDiffPart[] } = $props();
</script>

<dl class="structured-diff">
  {#each parts as part (part.key)}
    <div class="part-row">
      <dt>{part.label}</dt>
      <dd>
        {#if part.oldText !== null && part.changed}
          <del>{part.oldText}</del>
          <span class="arrow" aria-hidden="true">&rarr;</span>
          <ins>{part.newText}</ins>
        {:else}
          <span>{part.newText}</span>
        {/if}
      </dd>
    </div>
  {/each}
</dl>

<style>
  .structured-diff {
    display: grid;
    gap: var(--size-1);
    width: 100%;
    margin: 0;
    /* Open Props normalize gives dl its own font-size; keep the diff at the
       surrounding change-row size. */
    font-size: inherit;
  }

  .part-row {
    display: grid;
    grid-template-columns: minmax(8rem, max-content) minmax(0, 1fr);
    gap: var(--size-2);
    align-items: baseline;
  }

  dt {
    color: var(--color-text-muted);
    font-weight: 500;
  }

  dd {
    display: flex;
    min-width: 0;
    margin: 0;
    gap: var(--size-1);
    align-items: baseline;
    flex-wrap: wrap;
    overflow-wrap: anywhere;
  }

  del {
    opacity: 0.55;
  }

  ins {
    font-weight: 500;
    text-decoration: none;
  }

  .arrow {
    color: var(--color-text-muted);
  }

  @media (--breakpoint-narrow) {
    .part-row {
      grid-template-columns: 1fr;
      gap: 0;
    }
  }
</style>
