<script lang="ts">
  import TaxonomyListPage from './TaxonomyListPage.svelte';

  const items = [{ slug: 'alpha', name: 'Alpha' }];
</script>

{#snippet header()}
  <div class="custom-intro">
    <p>Rich introductory content here.</p>
  </div>
{/snippet}

<TaxonomyListPage catalogKey="tag" {items} loading={false} error={null} headerSnippet={header} />
