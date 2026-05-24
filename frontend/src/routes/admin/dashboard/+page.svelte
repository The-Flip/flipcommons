<script lang="ts">
  import { invalidate } from '$app/navigation';
  import Page from '$lib/components/Page.svelte';
  import { SITE_TITLE } from '$lib/constants';
  import { smartDate } from '$lib/dates';
  import MetricCard from './MetricCard.svelte';
  import { ADMIN_DASHBOARD_DEPEND_KEY } from './_dependencies';

  let { data } = $props();
  let stats = $derived(data.stats);

  const AUTO_REFRESH_MS = 60 * 60 * 1000; // one hour

  $effect(() => {
    const refresh = () => void invalidate(ADMIN_DASHBOARD_DEPEND_KEY);
    const id = setInterval(refresh, AUTO_REFRESH_MS);
    // The hourly setInterval is throttled while the tab is backgrounded,
    // and a bookmarked /a opened from a phone home screen will show whatever
    // generated_at was current when the tab was last foregrounded. Refresh
    // on visibility-restore so reopening the tab is the user's mental
    // "pull to refresh," not a stale snapshot waiting for the next tick.
    const onVisible = () => {
      if (document.visibilityState === 'visible') refresh();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      clearInterval(id);
      document.removeEventListener('visibilitychange', onVisible);
    };
  });
</script>

<svelte:head>
  <title>Admin — {SITE_TITLE}</title>
</svelte:head>

<Page width="narrow">
  <div class="cards">
    <MetricCard label="Signups" metric={stats.signups} />
    <MetricCard label="Edits" metric={stats.edits} />
    <MetricCard label="Uploads" metric={stats.uploads} />
  </div>
  <p class="footer">
    updated {smartDate(stats.generated_at)} · auto-refresh every hour
  </p>
</Page>

<style>
  .cards {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .footer {
    margin: 1rem 0 0;
    font-size: 0.8125rem;
    color: var(--color-text-muted);
    text-align: center;
  }
</style>
