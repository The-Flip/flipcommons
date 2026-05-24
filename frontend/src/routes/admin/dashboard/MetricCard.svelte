<script module lang="ts">
  const numberFormatter = new Intl.NumberFormat();
</script>

<script lang="ts">
  import { smartDate } from '$lib/dates';
  import type { AdminMetricSchema } from '$lib/api/schema';

  let {
    label,
    metric,
  }: {
    label: string;
    metric: AdminMetricSchema;
  } = $props();
</script>

<section class="card">
  <h2>{label}</h2>
  <dl class="windows">
    <div class="cell">
      <dt>24h</dt>
      <dd>{numberFormatter.format(metric.last_24h)}</dd>
    </div>
    <div class="cell">
      <dt>7d</dt>
      <dd>{numberFormatter.format(metric.last_7d)}</dd>
    </div>
    <div class="cell">
      <dt>Total</dt>
      <dd>{numberFormatter.format(metric.total)}</dd>
    </div>
  </dl>
  <p class="last-at">
    last: <span class="last-at-value">{metric.last_at ? smartDate(metric.last_at) : '∅'}</span>
  </p>
</section>

<style>
  .card {
    padding: 1rem;
    border: 1px solid var(--color-border);
    border-radius: 0.5rem;
    background: var(--color-surface);
  }

  h2 {
    margin: 0 0 0.5rem;
    font-size: 1rem;
    font-weight: 600;
  }

  .windows {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0.5rem;
    margin: 0 0 0.5rem;
  }

  .cell {
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  .cell dt {
    font-size: 0.75rem;
    color: var(--color-text-muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .cell dd {
    margin: 0;
    font-size: 1.5rem;
    font-variant-numeric: tabular-nums;
    font-weight: 600;
  }

  .last-at {
    margin: 0;
    font-size: 0.875rem;
    color: var(--color-text-muted);
  }

  .last-at-value {
    color: var(--color-text);
  }
</style>
