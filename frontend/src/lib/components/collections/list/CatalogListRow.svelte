<script lang="ts">
  /**
   * Standard catalog list-row content: an entity name and an optional
   * right-aligned count (e.g. "12 titles"). Rendered inside
   * `ServerPaginatedList`'s `<a class="item-row">`, which provides the flex
   * row + link; this owns only the `.item-name`/`.count` look. Entities with a
   * custom row (corporate entities, systems) supply their own snippet instead.
   */
  let {
    name,
    count = undefined,
    countNoun = 'title',
  }: {
    name: string;
    /** Display count shown on the right; omitted when undefined (e.g. credit-roles). */
    count?: number;
    /** Singular noun for the count label; pluralized with a trailing "s". */
    countNoun?: string;
  } = $props();
</script>

<span class="item-name">{name}</span>
{#if typeof count === 'number'}
  <span class="count">{count} {countNoun}{count === 1 ? '' : 's'}</span>
{/if}

<style>
  .item-name {
    font-size: var(--font-size-2);
    color: inherit;
    font-weight: 500;
    flex: 1;
  }

  .count {
    font-size: var(--font-size-1);
    color: var(--color-text-muted);
    flex-shrink: 0;
  }
</style>
