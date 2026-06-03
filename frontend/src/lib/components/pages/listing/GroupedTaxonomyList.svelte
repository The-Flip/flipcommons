<script
  lang="ts"
  generics="
		P extends { slug: string; name: string; title_count: number },
		C extends { slug: string; name: string; title_count: number }
	"
>
  import { resolveHref } from '$lib/utils';

  let {
    items,
    parentPath,
    childPath,
    getChildren,
  }: {
    items: P[];
    /** URL prefix for parent detail links, e.g. `/display-types`. */
    parentPath: string;
    /** URL prefix for child detail links, e.g. `/display-subtypes`. */
    childPath: string;
    getChildren: (parent: P) => C[];
  } = $props();
</script>

<ul class="parent-list">
  {#each items as parent (parent.slug)}
    {@const children = getChildren(parent)}
    <li class="parent-group">
      <a href={resolveHref(`${parentPath}/${parent.slug}`)} class="parent-row">
        <span class="parent-name">{parent.name}</span>
        <span class="count">
          {parent.title_count} title{parent.title_count === 1 ? '' : 's'}
        </span>
      </a>
      {#if children.length > 0}
        <ul class="child-list">
          {#each children as child (child.slug)}
            <li>
              <a href={resolveHref(`${childPath}/${child.slug}`)} class="child-row">
                <span class="child-name">{child.name}</span>
                <span class="count">
                  {child.title_count} title{child.title_count === 1 ? '' : 's'}
                </span>
              </a>
            </li>
          {/each}
        </ul>
      {/if}
    </li>
  {/each}
</ul>

<style>
  .parent-list,
  .child-list {
    list-style: none;
    padding: 0;
  }

  .parent-group {
    margin-bottom: var(--size-4);
  }

  .parent-row,
  .child-row {
    display: flex;
    align-items: baseline;
    padding: var(--size-3) 0;
    border-bottom: 1px solid var(--color-border-soft);
    text-decoration: none;
    color: var(--color-text);
  }

  .parent-row:hover,
  .child-row:hover {
    color: var(--color-link);
  }

  .parent-name {
    font-size: var(--font-size-3);
    font-weight: 600;
    flex: 1;
  }

  .child-list {
    margin-left: var(--size-6);
  }

  .child-name {
    font-size: var(--font-size-2);
    font-weight: 500;
    flex: 1;
  }

  .count {
    font-size: var(--font-size-1);
    color: var(--color-text-muted);
    flex-shrink: 0;
  }
</style>
