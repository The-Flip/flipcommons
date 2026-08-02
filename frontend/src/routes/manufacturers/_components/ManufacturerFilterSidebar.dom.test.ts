import { fireEvent, render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import ManufacturerFilterSidebarFixture from './ManufacturerFilterSidebar.fixture.svelte';
import { emptyMfrFilterState } from '$lib/filters/manufacturers';

async function selectFirstSearchableOption(
  user: ReturnType<typeof userEvent.setup>,
  label: RegExp,
) {
  const input = screen.getByRole('combobox', { name: label });
  await user.click(input);
  await fireEvent.pointerDown(screen.getByRole('option', { name: /usa/i }));

  return input;
}

function renderSidebar() {
  return render(ManufacturerFilterSidebarFixture);
}

describe('ManufacturerFilterSidebar', () => {
  it('updates the visible controls when filters change', async () => {
    const user = userEvent.setup();
    renderSidebar();

    // Exercise the real pointer-selection path used by SearchableSelect.
    const locationInput = await selectFirstSearchableOption(user, /location/i);
    expect(locationInput).toHaveValue('USA');

    const yearFrom = screen.getByLabelText('Year from') as HTMLInputElement;
    const yearTo = screen.getByLabelText('Year to') as HTMLInputElement;
    fireEvent.change(yearFrom, { target: { value: '1990' } });
    fireEvent.change(yearTo, { target: { value: '1995' } });
    expect(yearFrom).toHaveValue(1990);
    expect(yearTo).toHaveValue(1995);

    await user.click(screen.getByRole('button', { name: /solid state/i }));
    await vi.waitFor(() => {
      expect(screen.getByRole('button', { name: /clear all/i })).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /solid state/i })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  it('resets all visible controls when Clear all is clicked', async () => {
    const user = userEvent.setup();
    renderSidebar();

    await selectFirstSearchableOption(user, /location/i);
    const yearFrom = screen.getByLabelText('Year from') as HTMLInputElement;
    const yearTo = screen.getByLabelText('Year to') as HTMLInputElement;
    fireEvent.change(yearFrom, { target: { value: '1990' } });
    fireEvent.change(yearTo, { target: { value: '1995' } });
    await user.click(screen.getByRole('button', { name: /solid state/i }));
    await vi.waitFor(() => {
      expect(screen.getByRole('button', { name: /clear all/i })).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /clear all/i }));

    expect(screen.queryByRole('button', { name: /clear all/i })).not.toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: /location/i })).toHaveValue('');
    expect(yearFrom).toHaveValue(null);
    expect(yearTo).toHaveValue(null);
    expect(screen.getByRole('button', { name: /solid state/i })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  });
});

describe('ManufacturerFilterSidebar — disabled / cold-load', () => {
  it('renders without options (cold load) and disables every control', () => {
    render(ManufacturerFilterSidebarFixture, { noOptions: true, disabled: true });

    // The real filter chrome renders even with no options — labels + control boxes.
    expect(screen.getByRole('combobox', { name: /location/i })).toBeDisabled();
    expect(screen.getByRole('combobox', { name: /person/i })).toBeDisabled();
    expect(screen.getByLabelText('Year from')).toBeDisabled();
    expect(screen.getByLabelText('Year to')).toBeDisabled();
    // No option-backed pills render while options stream in.
    expect(screen.queryByRole('button', { name: /solid state/i })).not.toBeInTheDocument();
  });

  it('marks the sidebar aria-busy during a refetch while keeping controls live', () => {
    // Refetch state: prior options stay visible and interactive, but a fresh fetch is
    // in flight — only `aria-busy` signals it (no visual disable, so multi-select stays fast).
    render(ManufacturerFilterSidebarFixture, { busy: true });

    expect(screen.getByRole('complementary')).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('combobox', { name: /location/i })).toBeEnabled();
  });

  it('disables Clear all when a cold-loaded URL seeds a filter before options arrive', () => {
    // A deep link like /manufacturers?location=usa: the filter is active (so Clear all
    // shows) but options haven't streamed in yet, so the whole sidebar is disabled.
    render(ManufacturerFilterSidebarFixture, {
      noOptions: true,
      disabled: true,
      initialFilters: { ...emptyMfrFilterState(), location: 'usa' },
    });

    expect(screen.getByRole('button', { name: /clear all/i })).toBeDisabled();
  });
});
