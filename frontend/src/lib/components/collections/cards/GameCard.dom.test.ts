import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import GameCard from './GameCard.svelte';

describe('GameCard href', () => {
  it('links a title card to /titles/<slug> via the entity registry', () => {
    render(GameCard, {
      props: { entityType: 'title', slug: 'medieval-madness', name: 'Medieval Madness' },
    });

    expect(screen.getByRole('link')).toHaveAttribute('href', '/titles/medieval-madness');
  });

  it('links a model card to /models/<slug> via the entity registry', () => {
    render(GameCard, {
      props: { entityType: 'model', slug: 'medieval-madness-remake', name: 'Medieval Madness' },
    });

    expect(screen.getByRole('link')).toHaveAttribute('href', '/models/medieval-madness-remake');
  });
});

describe('GameCard visual identity', () => {
  it('renders an identical subtitle for a title and a model', () => {
    // The regression guard for the drift GameCard removed (font size, separator,
    // manufacturer fallback) — and against reintroducing a branch to restore it.
    const props = {
      slug: 'big-valley',
      name: 'Big Valley',
      manufacturerName: 'R.M.G.',
      year: 1970,
    };
    const title = render(GameCard, { props: { entityType: 'title' as const, ...props } });
    const titleSubtitle = title.container.querySelector('.card-subtitle')?.textContent;
    title.unmount();

    const model = render(GameCard, { props: { entityType: 'model' as const, ...props } });
    const modelSubtitle = model.container.querySelector('.card-subtitle')?.textContent;

    expect(titleSubtitle).toBe('R.M.G., 1970');
    expect(modelSubtitle).toBe(titleSubtitle);
  });
});

describe('GameCard manufacturer line', () => {
  it('shows the manufacturer name when known', () => {
    render(GameCard, {
      props: {
        entityType: 'title',
        slug: 'medieval-madness',
        name: 'Medieval Madness',
        manufacturerName: 'Williams',
      },
    });

    expect(screen.getByText(/Williams/)).toBeInTheDocument();
  });

  it('reads a missing manufacturer as "Unknown Manufacturer"', () => {
    render(GameCard, {
      props: { entityType: 'title', slug: 'big-ben', name: 'Big Ben', year: 1975 },
    });

    expect(screen.getByText(/Unknown Manufacturer/)).toBeInTheDocument();
  });

  it('omits the manufacturer line entirely when the caller suppresses it', () => {
    // Manufacturer and corporate-entity pages already name the manufacturer; repeating
    // it on every tile is noise, and "Unknown Manufacturer" is plainly wrong.
    render(GameCard, {
      props: {
        entityType: 'model',
        slug: 'big-ben',
        name: 'Big Ben',
        year: 1975,
        showManufacturer: false,
      },
    });

    expect(screen.queryByText(/Unknown Manufacturer/)).not.toBeInTheDocument();
    expect(screen.getByText('1975')).toBeInTheDocument();
  });
});
