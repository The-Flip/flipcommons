import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import HierarchicalTaxonomyMobileMetaBarFixture from './HierarchicalTaxonomyMobileMetaBar.fixture.svelte';

describe('HierarchicalTaxonomyMobileMetaBar', () => {
  it('renders parent label and links', () => {
    render(HierarchicalTaxonomyMobileMetaBarFixture);

    expect(screen.getByTestId('hierarchical-taxonomy-mobile-meta-bar')).toBeInTheDocument();
    expect(screen.getByText('Type of:')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Physical Feature' })).toHaveAttribute(
      'href',
      '/gameplay-features/physical-feature',
    );
  });

  it('renders alias label and joined values', () => {
    render(HierarchicalTaxonomyMobileMetaBarFixture, {
      props: { aliases: ['Pop', 'Side Kicker'] },
    });

    expect(screen.getByText('Also known as:')).toBeInTheDocument();
    expect(screen.getByText('Pop, Side Kicker')).toBeInTheDocument();
  });

  it('joins multiple parents with commas', () => {
    render(HierarchicalTaxonomyMobileMetaBarFixture, {
      props: {
        parents: [
          { name: 'Physical Feature', public_id: 'physical-feature' },
          { name: 'Defense', public_id: 'defense' },
        ],
      },
    });

    expect(screen.getByRole('link', { name: 'Physical Feature' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Defense' })).toBeInTheDocument();
  });

  it('separates parent links with ", " (comma followed by a space)', () => {
    // Regression: Svelte's whitespace handling collapsed a literal ", "
    // between links into bare ",". Wrapping in a span preserves it.
    render(HierarchicalTaxonomyMobileMetaBarFixture, {
      props: {
        parents: [
          { name: 'Blackjack', public_id: 'blackjack' },
          { name: 'Cards', public_id: 'cards' },
          { name: 'Gambling', public_id: 'gambling' },
        ],
        aliases: [],
      },
    });

    const bar = screen.getByTestId('hierarchical-taxonomy-mobile-meta-bar');
    // `textContent` normalizes internal whitespace; compare against a form
    // that would read "Type of: Blackjack, Cards, Gambling" (not "Blackjack,Cards,Gambling").
    const normalized = (bar.textContent ?? '').replace(/\s+/g, ' ').trim();
    expect(normalized).toContain('Blackjack, Cards, Gambling');
  });

  it('renders nothing when both parents and aliases are empty', () => {
    render(HierarchicalTaxonomyMobileMetaBarFixture, {
      props: { parents: [], aliases: [] },
    });

    expect(screen.queryByTestId('hierarchical-taxonomy-mobile-meta-bar')).toBeNull();
  });

  it('renders only the alias section when there are no parents', () => {
    render(HierarchicalTaxonomyMobileMetaBarFixture, {
      props: { parents: [], aliases: ['Pop'] },
    });

    expect(screen.getByTestId('hierarchical-taxonomy-mobile-meta-bar')).toBeInTheDocument();
    expect(screen.queryByText('Type of:')).toBeNull();
    expect(screen.getByText('Also known as:')).toBeInTheDocument();
  });

  it('renders only the parents section when there are no aliases', () => {
    render(HierarchicalTaxonomyMobileMetaBarFixture, {
      props: { aliases: [] },
    });

    expect(screen.getByText('Type of:')).toBeInTheDocument();
    expect(screen.queryByText('Also known as:')).toBeNull();
  });

  it('honors per-entity label overrides (themes labels)', () => {
    render(HierarchicalTaxonomyMobileMetaBarFixture, {
      props: {
        basePath: '/themes',
        parents: [{ name: 'Sports', public_id: 'sports' }],
        parentLabel: 'Parent themes',
      },
    });

    expect(screen.getByText('Parent themes:')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Sports' })).toHaveAttribute('href', '/themes/sports');
  });
});
