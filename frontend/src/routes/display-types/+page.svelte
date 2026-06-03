<script lang="ts">
  import GroupedTaxonomyList from '$lib/components/pages/listing/GroupedTaxonomyList.svelte';
  import TaxonomyListPage from '$lib/components/pages/listing/TaxonomyListPage.svelte';

  let { data } = $props();
</script>

<TaxonomyListPage catalogKey="display-type" items={data.items} canCreate>
  {#snippet headerSnippet()}
    <p class="overview">
      A <strong>display type</strong> is the technology a game machine uses to show the player's
      score and — in later eras — animations, artwork, and video. Early
      <a href="/technology-generations/electromechanical">electromechanical</a> (EM) machines
      totaled points with banks of <a href="/display-types/backglass-lights">backglass lights</a>,
      then moved to the clattering mechanical <a href="/display-types/score-reels">score reels</a>
      that defined the EM golden age. The
      <a href="/technology-generations/solid-state">solid-state</a>
      era replaced reels with glowing
      <a href="/display-types/alphanumeric">alphanumeric</a> LED segments, which in 1991 gave way to
      the iconic orange <a href="/display-types/dot-matrix">dot-matrix display</a> that
      <a href="/manufacturers/williams">Williams</a> introduced on
      <a href="/titles/funhouse"><em>Funhouse</em></a> and
      <a href="/titles/the-addams-family"><em>The Addams Family</em></a>. A handful of hybrids —
      <a href="/manufacturers/bally">Bally</a>'s
      <a href="/titles/baby-pac-man"><em>Baby Pac-Man</em></a> and Williams' Pinball 2000 — used
      <a href="/display-types/cga">CGA monitors</a> instead. Today's machines, starting with
      <a href="/manufacturers/jersey-jack">Jersey Jack</a>'s
      <a href="/titles/the-wizard-of-oz"><em>The Wizard of Oz</em></a> in 2013, ship with full-color
      <a href="/display-types/lcd">LCD screens</a>.
    </p>
  {/snippet}

  {#snippet listSnippet(items)}
    <GroupedTaxonomyList
      {items}
      parentPath="/display-types"
      childPath="/display-subtypes"
      getChildren={(t) => t.subtypes}
    />
  {/snippet}
</TaxonomyListPage>

<style>
  .overview {
    font-size: var(--font-size-2);
    color: var(--color-text-muted);
    margin-top: var(--size-2);
    max-width: 42rem;
    line-height: 1.5;
  }

  .overview a {
    color: var(--color-link);
  }
</style>
