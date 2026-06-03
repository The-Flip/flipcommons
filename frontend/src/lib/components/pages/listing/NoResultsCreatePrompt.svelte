<script lang="ts">
  interface Props {
    entityLabel: string;
    query: string;
    createHref: string;
  }

  let { entityLabel, query, createHref }: Props = $props();
</script>

<div class="prompt">
  <p>
    The {entityLabel} "{query}" does not exist.
    <a href={createHref}>Create?</a>
  </p>
</div>

<style>
  .prompt {
    text-align: center;
    padding: var(--size-6) 0;
    color: var(--color-text-muted);
  }

  .prompt p {
    margin: 0;
  }

  a {
    color: var(--color-link);
    font-weight: 600;
  }
</style>
