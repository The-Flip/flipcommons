<script lang="ts" generics="T extends { slug: string }">
  import type { Snippet } from 'svelte';
  import InfiniteScroll from '$lib/components/collections/InfiniteScroll.svelte';
  import { resolveHref } from '$lib/utils';

  /**
   * Row-list analog of `ServerPaginatedGrid`: the same server-paginated
   * infinite-scroll loader, rendered as a `<ul>` of linked rows instead of a
   * card grid. Owns the row chrome (`<li><a class="item-row">` + the link to
   * `${basePath}/${item.slug}`); the caller's `children` snippet fills each
   * row's content (use `CatalogListRow` for the standard name+count look).
   *
   * `resolveHref` (not `resolve`) because the route *pattern* isn't known at
   * this generic call site — the documented fallback, same as the
   * taxonomy/grouped list pages.
   */
  let {
    items,
    hasMore,
    loadMore,
    basePath,
    children,
  }: {
    items: T[];
    hasMore: boolean;
    loadMore: () => void;
    /** Detail-page base, e.g. `/franchises`; each row links to `${basePath}/${slug}`. */
    basePath: string;
    children: Snippet<[T]>;
  } = $props();
</script>

<InfiniteScroll {hasMore} onSentinel={loadMore}>
  <ul class="item-list">
    {#each items as item (item.slug)}
      <li>
        <a href={resolveHref(`${basePath}/${item.slug}`)} class="item-row">
          {@render children(item)}
        </a>
      </li>
    {/each}
  </ul>
</InfiniteScroll>

<style>
  /* The row chrome. `.item-name`/`.count` live in CatalogListRow (the row
     content), since scoped styles only reach markup defined in the same component. */
  .item-list {
    list-style: none;
    padding: 0;
  }

  .item-row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--size-4);
    padding: var(--size-3) 0;
    border-bottom: 1px solid var(--color-border-soft);
    text-decoration: none;
    color: var(--color-text);
  }

  .item-row:hover {
    color: var(--color-link);
  }
</style>
