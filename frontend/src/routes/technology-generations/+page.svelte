<script lang="ts">
  import GroupedTaxonomyList from '$lib/components/pages/listing/GroupedTaxonomyList.svelte';
  import TaxonomyListPage from '$lib/components/pages/listing/TaxonomyListPage.svelte';

  let { data } = $props();
</script>

<TaxonomyListPage catalogKey="technology-generation" items={data.items} canCreate>
  {#snippet headerSnippet()}
    <p class="overview">
      A <strong>technology generation</strong> is a major era in how pinball machines were built —
      the underlying engine driving scoring, logic, and feedback.
      <a href="/technology-generations/pure-mechanical">Pure mechanical</a> machines of the 1920s
      and early '30s were pure gravity and springs: no wires, no bells, just a plunger and a
      pin-studded playfield. The
      <a href="/technology-generations/electromechanical">electromechanical</a>
      era that followed wired playfields with relays, solenoids, and rotating
      <a href="/display-types/score-reels">score reels</a> —
      <a href="/manufacturers/gottlieb">Gottlieb</a>, <a href="/manufacturers/bally">Bally</a>, and
      <a href="/manufacturers/williams">Williams</a> spent three decades perfecting the form, and
      <a href="/manufacturers/gottlieb">Gottlieb</a>'s
      <a href="/titles/humpty-dumpty"><em>Humpty Dumpty</em></a> introduced the
      <a href="/gameplay-features/flippers">flipper</a> in 1947. The
      <a href="/technology-generations/solid-state">solid-state</a> revolution began in 1977 with
      <a href="/manufacturers/bally">Bally</a>'s
      <a href="/titles/freedom"><em>Freedom</em></a>, replacing relays with a microprocessor and
      opening the door to <a href="/gameplay-features/multiball">multiball</a>, speech,
      <a href="/display-types/dot-matrix">dot-matrix</a> animation, and the deep rule sheets of
      titles like <a href="/titles/the-addams-family"><em>The Addams Family</em></a>,
      <a href="/titles/twilight-zone"><em>Twilight Zone</em></a>, and
      <a href="/titles/medieval-madness"><em>Medieval Madness</em></a>. Every machine built today
      still belongs to that solid-state lineage.
    </p>
  {/snippet}

  {#snippet listSnippet(items)}
    <GroupedTaxonomyList
      {items}
      parentPath="/technology-generations"
      childPath="/technology-subgenerations"
      getChildren={(g) => g.subgenerations}
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
