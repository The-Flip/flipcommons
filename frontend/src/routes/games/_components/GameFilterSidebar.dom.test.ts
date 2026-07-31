import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import GameFilterSidebarFixture from './GameFilterSidebar.fixture.svelte';

describe('GameFilterSidebar — cold load (no options)', () => {
  it('renders the filter chrome without crashing when options are undefined', () => {
    // Pins the guards on every `filterOptions`-reading derivation — notably
    // `playerCountChipOptions`, which bypasses `toOptions` and would otherwise
    // dereference `undefined.player_count` on a cold load.
    render(GameFilterSidebarFixture);

    expect(screen.getByRole('combobox', { name: /manufacturer/i })).toBeDisabled();
    expect(screen.getByRole('combobox', { name: /relationship/i })).toBeDisabled();
    expect(screen.getByRole('combobox', { name: /game format/i })).toBeDisabled();
    expect(screen.getByRole('combobox', { name: /production status/i })).toBeDisabled();
    expect(screen.getByRole('combobox', { name: /cabinet/i })).toBeDisabled();
    expect(screen.getByLabelText('Year from')).toBeDisabled();
    // The option-backed pill groups render just their labels (no pills) while loading.
    expect(screen.getByText('Player count')).toBeInTheDocument();
    expect(screen.getByText('Tech generation')).toBeInTheDocument();
  });
});
