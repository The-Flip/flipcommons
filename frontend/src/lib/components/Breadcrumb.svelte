<script lang="ts">
  import { resolveHref } from '$lib/utils';

  export type Crumb = { label: string; href: string };

  // House pattern: the breadcrumb shows only the ancestor trail (all links) and
  // NOT the current page — that lives in the page's own heading. Callers pass
  // just the ancestors in `crumbs`.
  let { crumbs }: { crumbs: Crumb[] } = $props();
</script>

<nav aria-label="Breadcrumb" class="breadcrumb">
  <ol>
    {#each crumbs as crumb (crumb.href)}
      <li>
        <a href={resolveHref(crumb.href)}>{crumb.label}</a>
      </li>
    {/each}
  </ol>
</nav>

<style>
  ol {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    list-style: none;
    padding: 0;
    margin: 0;
    gap: var(--size-1);
    font-size: var(--font-size-1);
    color: var(--color-text-muted);
  }

  li:not(:last-child)::after {
    content: '/';
    margin-left: var(--size-1);
    color: var(--color-text-muted);
  }

  a {
    color: var(--color-text-muted);
    text-decoration: none;
  }

  a:hover {
    color: var(--color-text);
    text-decoration: underline;
  }
</style>
