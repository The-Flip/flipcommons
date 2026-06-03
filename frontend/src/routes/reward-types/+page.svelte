<script lang="ts">
  import { resolve } from '$app/paths';
  import client from '$lib/api/client';
  import { unwrapPage } from '$lib/paginated-loader.svelte';
  import CatalogListing from '$lib/components/pages/listing/CatalogListing.svelte';
  import CatalogListRow from '$lib/components/collections/list/CatalogListRow.svelte';

  let { data } = $props();

  // Typed page fetcher: the `/api/reward-types/` path literal is baked in here so
  // the response stays typed, then flows generically through CatalogListing.
  // Reads the committed `q` at call time.
  const fetchPage = async (page: number) => {
    const res = await client.GET('/api/reward-types/', {
      params: { query: { q: data.q, page } },
    });
    return unwrapPage(res.data);
  };
</script>

<CatalogListing
  catalogKey="reward-type"
  initial={{ items: data.items, count: data.count }}
  {fetchPage}
  q={data.q}
  canCreate
>
  {#snippet headerSnippet()}
    <div class="intro">
      <p>
        Pinball machines have offered players various rewards since the earliest coin-operated
        games. The simplest reward — and the one that defined the legal landscape for decades — is
        the
        <a href={resolve('/reward-types/replay')}>replay</a>: a free game awarded for reaching a
        score threshold, achieving a specified feat, or landing on a replay score set by the
        operator. Replays required no additional coins and were accepted in most jurisdictions as a
        game of skill rather than gambling.
      </p>
      <p>
        The <a href={resolve('/reward-types/add-a-ball')}>add-a-ball</a> mechanic emerged in the early
        1960s as an alternative in localities where replays were prohibited. Rather than granting a free
        game, the machine added an extra ball to the current game — a distinction that satisfied anti-gambling
        ordinances in many cities and states. Some manufacturers produced dual-purpose machines switchable
        between replay and add-a-ball modes depending on where they were operated.
      </p>
      <p>
        Solid-state machines of the late 1970s and 1980s introduced new reward categories.
        <a href={resolve('/reward-types/free-play')}>Free play</a> mode (typically operator-set)
        allowed unlimited games without coins, common in home use and arcades experimenting with
        flat-rate admission. <a href={resolve('/reward-types/novelty')}>Novelty</a> machines awarded
        no replays at all, sidestepping gambling concerns entirely by design.
        <a href={resolve('/reward-types/cash-payout')}>Cash-payout</a> machines, used in certain
        jurisdictions, dispensed coins or tokens directly — these operated under gaming regulations
        where applicable. <a href={resolve('/reward-types/ticket-payout')}>Ticket-payout</a>
        machines dispensed paper tickets redeemable for prizes, a format that became prevalent in family
        entertainment centers from the 1980s onward.
      </p>
      <p>
        The reward type of a given machine often depended as much on where it was sold and operated
        as on the manufacturer's design intent. Many titles were produced in multiple reward
        configurations, and operators frequently modified machines in the field to comply with local
        regulations.
      </p>
    </div>
  {/snippet}

  {#snippet children(rewardType)}
    <CatalogListRow name={rewardType.name} count={rewardType.title_count} />
  {/snippet}
</CatalogListing>

<style>
  .intro {
    margin-top: var(--size-4);
  }

  .intro p {
    font-size: var(--font-size-2);
    color: var(--color-text-muted);
    margin-bottom: var(--size-4);
    line-height: 1.7;
  }
</style>
