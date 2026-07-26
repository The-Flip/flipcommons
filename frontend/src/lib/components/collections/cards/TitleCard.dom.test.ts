import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import TitleCard from './TitleCard.svelte';

describe('TitleCard manufacturer line', () => {
  it('shows the manufacturer name when known', () => {
    render(TitleCard, {
      props: { slug: 'medieval-madness', name: 'Medieval Madness', manufacturerName: 'Williams' },
    });

    expect(screen.getByText(/Williams/)).toBeInTheDocument();
  });

  it('reads a missing manufacturer as "Unknown Manufacturer"', () => {
    render(TitleCard, { props: { slug: 'big-ben', name: 'Big Ben', year: 1975 } });

    expect(screen.getByText(/Unknown Manufacturer/)).toBeInTheDocument();
  });

  it('omits the manufacturer line entirely when the caller suppresses it', () => {
    // Manufacturer and corporate-entity pages already name the manufacturer; repeating
    // it on every tile is noise, and "Unknown Manufacturer" is plainly wrong.
    render(TitleCard, {
      props: { slug: 'big-ben', name: 'Big Ben', year: 1975, showManufacturer: false },
    });

    expect(screen.queryByText(/Unknown Manufacturer/)).not.toBeInTheDocument();
    expect(screen.getByText('1975')).toBeInTheDocument();
  });
});
