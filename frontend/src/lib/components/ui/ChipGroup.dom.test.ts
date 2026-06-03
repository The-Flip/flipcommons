import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import ChipGroup from './ChipGroup.svelte';

const OPTIONS = [
  { value: 'em', label: 'Electromechanical', count: 3 },
  { value: 'ss', label: 'Solid state', count: 0 },
];

describe('ChipGroup', () => {
  it('disables a zero-count option that is not selected', () => {
    render(ChipGroup, { options: OPTIONS, selected: 'em' });
    expect(screen.getByRole('button', { name: /Solid state/ })).toBeDisabled();
  });

  it('keeps a selected zero-count option clickable so it can be deselected', async () => {
    // The backend restores an active filter at count 0 when a conflicting filter
    // prunes it (see _with_selected); the sidebar control must still let the user
    // toggle that selection off rather than stranding it.
    const user = userEvent.setup();
    const onchange = vi.fn();
    render(ChipGroup, { options: OPTIONS, selected: 'ss', onchange });

    const chip = screen.getByRole('button', { name: /Solid state/ });
    expect(chip).not.toBeDisabled();

    await user.click(chip);
    expect(onchange).toHaveBeenCalledWith(null);
  });

  it('disables every chip when disabled (options streaming in)', async () => {
    // Even an otherwise-clickable chip (non-zero count, or the selected one) is inert
    // while the sidebar holds the control during the first/cold load.
    const user = userEvent.setup();
    const onchange = vi.fn();
    render(ChipGroup, { options: OPTIONS, selected: 'em', disabled: true, onchange });

    const active = screen.getByRole('button', { name: /Electromechanical/ });
    expect(active).toBeDisabled();
    await user.click(active);
    expect(onchange).not.toHaveBeenCalled();
  });
});
