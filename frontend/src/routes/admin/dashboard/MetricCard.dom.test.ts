import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import MetricCard from './MetricCard.svelte';

describe('MetricCard', () => {
  // Compute via Intl directly so the assertion stays locale-agnostic —
  // CI may format thousands with comma, dot, or non-breaking space.
  const fmt = (n: number) => new Intl.NumberFormat().format(n);

  it('renders the three windowed counts and a formatted timestamp', () => {
    render(MetricCard, {
      label: 'Signups',
      metric: {
        last_24h: 3,
        last_7d: 12,
        total: 847,
        last_at: '2026-05-18T18:30:00Z',
      },
    });
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Signups');
    expect(screen.getByText(fmt(3))).toBeInTheDocument();
    expect(screen.getByText(fmt(12))).toBeInTheDocument();
    expect(screen.getByText(fmt(847))).toBeInTheDocument();
    // smartDate output varies by locale/now; just assert the empty-state
    // marker is NOT rendered when last_at is set.
    expect(screen.queryByText('∅')).not.toBeInTheDocument();
  });

  it('renders ∅ in place of the timestamp when last_at is null', () => {
    render(MetricCard, {
      label: 'Edits',
      metric: { last_24h: 0, last_7d: 0, total: 0, last_at: null },
    });
    expect(screen.getByText('∅')).toBeInTheDocument();
  });

  it('thousands-separates large totals via Intl.NumberFormat', () => {
    render(MetricCard, {
      label: 'Edits',
      metric: { last_24h: 0, last_7d: 0, total: 5213, last_at: null },
    });
    expect(screen.getByText(fmt(5213))).toBeInTheDocument();
  });
});
