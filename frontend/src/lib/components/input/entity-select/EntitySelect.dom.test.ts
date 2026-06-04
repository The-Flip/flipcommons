import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { EntityOption } from '$lib/api/entity-autocomplete';

const DATA: EntityOption[] = [
  { value: 'stern', label: 'Stern Pinball', sublabel: 'USA' },
  { value: 'bally', label: 'Bally', sublabel: null },
  { value: 'williams', label: 'Williams', sublabel: null },
];

const autocompleteEntities = vi.fn((_type: string, q: string) =>
  Promise.resolve(DATA.filter((d) => d.label.toLowerCase().includes(q.toLowerCase()))),
);

// Partial mock: stub only the network call; keep the real AUTOCOMPLETE_RESULT_LIMIT.
vi.mock('$lib/api/entity-autocomplete', async (importOriginal) => ({
  ...(await importOriginal<typeof import('$lib/api/entity-autocomplete')>()),
  autocompleteEntities: (type: string, q: string) => autocompleteEntities(type, q),
}));

// Import after the mock is registered.
const { default: EntitySelect } = await import('./EntitySelect.svelte');

function getCombobox() {
  return screen.getByRole('combobox', { name: /manufacturer/i });
}

function renderSelect(props: Record<string, unknown> = {}) {
  return render(EntitySelect, {
    type: 'manufacturer',
    label: 'Manufacturer',
    placeholder: 'Search manufacturers...',
    ...props,
  });
}

beforeEach(() => {
  autocompleteEntities.mockClear();
});

describe('EntitySelect', () => {
  it('renders the initial selection with no search', () => {
    renderSelect({ selected: 'stern', initialSelection: DATA[0] });

    expect(getCombobox()).toHaveValue('Stern Pinball');
    expect(autocompleteEntities).not.toHaveBeenCalled();
  });

  it('opens on focus and fires an empty-query search for the top-N', async () => {
    const user = userEvent.setup();
    renderSelect();

    await user.click(getCombobox());

    expect(autocompleteEntities).toHaveBeenCalledWith('manufacturer', '');
    expect(await screen.findByRole('option', { name: /stern pinball/i })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /bally/i })).toBeInTheDocument();
  });

  it('searches by the typed query and shows the sublabel', async () => {
    const user = userEvent.setup();
    renderSelect();

    await user.click(getCombobox());
    await user.type(getCombobox(), 'stern');

    // The empty-q focus search seeds all rows; wait for the 'stern' search to
    // replace them (debounced) before asserting the narrowed result.
    await waitFor(() =>
      expect(screen.queryByRole('option', { name: /bally/i })).not.toBeInTheDocument(),
    );
    expect(screen.getByRole('option', { name: /stern pinball/i })).toBeInTheDocument();
    expect(screen.getByText('USA')).toBeInTheDocument();
    expect(autocompleteEntities).toHaveBeenLastCalledWith('manufacturer', 'stern');
  });

  it('shows a "type to search" hint only when the result set is capped', async () => {
    const user = userEvent.setup();
    const full = Array.from({ length: 20 }, (_, i) => ({
      value: `m-${i}`,
      label: `Maker ${i}`,
      sublabel: null,
    }));
    autocompleteEntities.mockResolvedValueOnce(full);
    renderSelect();

    await user.click(getCombobox());
    expect(await screen.findByText(/showing first 20/i)).toBeInTheDocument();
  });

  it('shows no cap hint when fewer than a full page come back', async () => {
    const user = userEvent.setup();
    renderSelect();

    await user.click(getCombobox());
    await screen.findByRole('option', { name: /stern pinball/i });
    expect(screen.queryByText(/type to search/i)).not.toBeInTheDocument();
  });

  it('selects with keyboard, binding the value and showing its label', async () => {
    const user = userEvent.setup();
    renderSelect();

    await user.click(getCombobox());
    await screen.findByRole('option', { name: /stern pinball/i });
    await user.keyboard('{ArrowDown}{Enter}');

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    expect(getCombobox()).toHaveValue('Stern Pinball');
    expect(screen.getByRole('button', { name: /clear selection/i })).toBeInTheDocument();
  });

  it('selects on pointer down (the real interaction path)', async () => {
    const user = userEvent.setup();
    renderSelect();

    await user.click(getCombobox());
    const option = await screen.findByRole('option', { name: /bally/i });
    await fireEvent.pointerDown(option);

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    expect(getCombobox()).toHaveValue('Bally');
  });

  it('clears a selection with the clear button', async () => {
    const user = userEvent.setup();
    renderSelect({ selected: 'stern', initialSelection: DATA[0] });

    await user.click(screen.getByRole('button', { name: /clear selection/i }));

    expect(getCombobox()).toHaveValue('');
    expect(screen.queryByRole('button', { name: /clear selection/i })).not.toBeInTheDocument();
  });

  it('hides the clear button when required', () => {
    renderSelect({ selected: 'stern', initialSelection: DATA[0], required: true });

    expect(getCombobox()).toHaveValue('Stern Pinball');
    expect(screen.queryByRole('button', { name: /clear selection/i })).not.toBeInTheDocument();
  });

  it('closes and resets the query on escape', async () => {
    const user = userEvent.setup();
    renderSelect();

    await user.click(getCombobox());
    await user.type(getCombobox(), 'st');
    await user.keyboard('{Escape}');

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    expect(getCombobox()).toHaveValue('');
    expect(getCombobox()).not.toHaveFocus();
  });

  it('recovers from a failed search: clears loading and shows "No matches"', async () => {
    autocompleteEntities.mockRejectedValueOnce(new Error('boom'));
    const user = userEvent.setup();
    renderSelect();

    await user.click(getCombobox());

    // No stuck "Searching…", no unhandled rejection — the catch degrades to empty.
    expect(await screen.findByText('No matches')).toBeInTheDocument();
    expect(screen.queryByText('Searching…')).not.toBeInTheDocument();
  });

  it('refreshes the displayed label when initialSelection is swapped after mount', async () => {
    const { rerender } = renderSelect({ selected: 'stern', initialSelection: DATA[0] });
    expect(getCombobox()).toHaveValue('Stern Pinball');

    // Parent loads/swaps the saved ref on the live instance.
    await rerender({ type: 'manufacturer', selected: 'bally', initialSelection: DATA[1] });

    expect(getCombobox()).toHaveValue('Bally');
  });

  it('reopens via ArrowDown after a selection without pre-highlighting a row', async () => {
    const user = userEvent.setup();
    renderSelect();

    await user.click(getCombobox());
    await screen.findByRole('option', { name: /stern pinball/i });
    await user.keyboard('{ArrowDown}{Enter}'); // select; closes but keeps focus

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();

    await user.keyboard('{ArrowDown}'); // reopen from the focused, closed input
    expect(await screen.findByRole('listbox')).toBeInTheDocument();
    // Async results: opening highlights nothing until the user arrows again.
    expect(document.querySelectorAll('[data-active="true"]')).toHaveLength(0);
  });

  it('wires aria-describedby to the rendered error message', () => {
    renderSelect({ error: 'Pick one' });

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Pick one');
    expect(getCombobox()).toHaveAttribute('aria-invalid', 'true');
    expect(getCombobox()).toHaveAttribute('aria-describedby', alert.id);
  });

  it('cancels a pending debounce timer on unmount (no late fetch into a dead component)', async () => {
    vi.useFakeTimers();
    try {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      const rendered = renderSelect();

      await user.click(getCombobox()); // empty-q fires immediately
      await user.type(getCombobox(), 'st'); // arms the debounce timer
      rendered.unmount();

      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it('is inert when disabled: input disabled and the listbox never opens', async () => {
    const user = userEvent.setup();
    renderSelect({ disabled: true });

    expect(getCombobox()).toBeDisabled();
    await user.click(getCombobox());
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    expect(autocompleteEntities).not.toHaveBeenCalled();
  });
});
