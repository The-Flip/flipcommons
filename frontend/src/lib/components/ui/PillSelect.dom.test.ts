import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import PillSelectFixture from './PillSelect.fixture.svelte';

describe('PillSelect', () => {
  it('shows the current option label on the trigger', () => {
    render(PillSelectFixture, { value: 'backglass' });
    expect(screen.getByRole('button', { name: 'Image category: backglass' })).toHaveTextContent(
      'backglass',
    );
  });

  it('shows the placeholder and "none" in the accessible name when value is null', () => {
    render(PillSelectFixture, { value: null });
    const trigger = screen.getByRole('button', { name: 'Image category: none' });
    expect(trigger).toHaveTextContent('—');
  });

  it('opens to a listbox of all options with the current one selected', async () => {
    const user = userEvent.setup();
    render(PillSelectFixture, { value: 'playfield' });

    const trigger = screen.getByRole('button', { name: 'Image category: playfield' });
    await user.click(trigger);

    expect(screen.getByRole('listbox')).toBeInTheDocument();
    const options = screen.getAllByRole('option');
    expect(options.map((o) => o.textContent?.trim())).toEqual([
      'playfield',
      'backglass',
      'cabinet',
    ]);
    expect(screen.getByRole('option', { name: 'playfield' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });

  it('fires onchange when a different option is picked', async () => {
    const user = userEvent.setup();
    const onchange = vi.fn();
    render(PillSelectFixture, { value: 'playfield', onchange });

    await user.click(screen.getByRole('button', { name: 'Image category: playfield' }));
    await user.click(screen.getByRole('option', { name: 'cabinet' }));

    expect(onchange).toHaveBeenCalledTimes(1);
    expect(onchange).toHaveBeenCalledWith('cabinet');
  });

  it('does NOT fire onchange when the current option is re-selected', async () => {
    const user = userEvent.setup();
    const onchange = vi.fn();
    render(PillSelectFixture, { value: 'playfield', onchange });

    await user.click(screen.getByRole('button', { name: 'Image category: playfield' }));
    await user.click(screen.getByRole('option', { name: 'playfield' }));

    expect(onchange).not.toHaveBeenCalled();
  });

  it('blocks opening when disabled', async () => {
    const user = userEvent.setup();
    render(PillSelectFixture, { disabled: true });

    const trigger = screen.getByRole('button', { name: 'Image category: playfield' });
    expect(trigger).toBeDisabled();

    await user.click(trigger);
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });
});
