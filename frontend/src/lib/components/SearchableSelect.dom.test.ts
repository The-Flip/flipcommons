import { fireEvent, render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import SearchableSelect from './SearchableSelect.svelte';
import SearchableSelectClipFixture from './SearchableSelect.clip.fixture.svelte';

const OPTIONS = [
  { slug: 'stern', label: 'Stern Pinball', count: 5 },
  { slug: 'bally', label: 'Bally', count: 3 },
  { slug: 'williams', label: 'Williams', count: 0 },
];

function renderSingle(props: Partial<{ selected: string | null; allowZeroCount: boolean }> = {}) {
  return render(SearchableSelect, {
    options: OPTIONS,
    label: 'Manufacturer',
    placeholder: 'Search manufacturers...',
    selected: null,
    ...props,
  });
}

function renderMulti(props: Partial<{ selected: string[]; allowZeroCount: boolean }> = {}) {
  return render(SearchableSelect, {
    options: OPTIONS,
    label: 'Manufacturer',
    placeholder: 'Search manufacturers...',
    multi: true,
    selected: [],
    ...props,
  });
}

function getCombobox() {
  return screen.getByRole('combobox', { name: /manufacturer/i });
}

describe('SearchableSelect', () => {
  it('opens the listbox on focus', async () => {
    const user = userEvent.setup();
    renderSingle();

    await user.click(getCombobox());

    expect(screen.getByRole('listbox')).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /stern pinball/i })).toBeInTheDocument();
  });

  it('filters options from the typed query', async () => {
    const user = userEvent.setup();
    renderSingle();

    await user.click(getCombobox());
    await user.type(getCombobox(), 'st');

    expect(screen.getByRole('option', { name: /stern pinball/i })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /bally/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /williams/i })).not.toBeInTheDocument();
  });

  it('supports arrow-key navigation and enter selection', async () => {
    const user = userEvent.setup();
    renderSingle();

    await user.click(getCombobox());
    await user.keyboard('{ArrowDown}{Enter}');

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    expect(getCombobox()).toHaveValue('Stern Pinball');
    expect(screen.getByRole('button', { name: /clear selection/i })).toBeInTheDocument();
  });

  it('selects an option with pointer down to match the real interaction path', async () => {
    const user = userEvent.setup();
    renderSingle();

    await user.click(getCombobox());

    const option = screen.getByRole('option', { name: /stern pinball/i });
    await fireEvent.pointerDown(option);

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    expect(getCombobox()).toHaveValue('Stern Pinball');
  });

  it('closes and resets the query on escape', async () => {
    const user = userEvent.setup();
    renderSingle();

    await user.click(getCombobox());
    await user.type(getCombobox(), 'st');
    await user.keyboard('{Escape}');

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    expect(getCombobox()).toHaveValue('');
    expect(getCombobox()).not.toHaveFocus();
  });

  it('closes on pointer down outside the component', async () => {
    const user = userEvent.setup();
    renderSingle();

    await user.click(getCombobox());
    expect(screen.getByRole('listbox')).toBeInTheDocument();

    fireEvent.pointerDown(document.body);

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    expect(getCombobox()).toHaveValue('');
  });

  it('clears a single selected value with the clear button', async () => {
    const user = userEvent.setup();
    renderSingle({ selected: 'stern' });

    expect(getCombobox()).toHaveValue('Stern Pinball');

    await user.click(screen.getByRole('button', { name: /clear selection/i }));

    expect(getCombobox()).toHaveValue('');
    expect(screen.queryByRole('button', { name: /clear selection/i })).not.toBeInTheDocument();
  });

  it('removes a selected tag in multi-select mode', async () => {
    const user = userEvent.setup();
    renderMulti({ selected: ['stern', 'bally'] });

    expect(screen.getByText('Stern Pinball')).toBeInTheDocument();
    expect(screen.getByText('Bally')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /remove bally/i }));

    expect(screen.queryByText('Bally')).not.toBeInTheDocument();
    expect(screen.getByText('Stern Pinball')).toBeInTheDocument();
  });

  it('keeps the multi-select input empty when a single value is selected (chip speaks for it)', () => {
    renderMulti({ selected: ['stern'] });

    // The selection is already rendered as a chip; the input must not
    // duplicate it as its value, which would read as a search query.
    expect(getCombobox()).toHaveValue('');
    expect(screen.getByText('Stern Pinball')).toBeInTheDocument();
  });

  it('summarizes the multi-select input when more than one value is selected', () => {
    renderMulti({ selected: ['stern', 'bally'] });

    expect(getCombobox()).toHaveValue('2 selected');
  });

  it('marks zero-count options disabled and does not select them by keyboard by default', async () => {
    const user = userEvent.setup();
    renderSingle({ allowZeroCount: false });

    await user.click(getCombobox());
    await user.type(getCombobox(), 'wil');

    const williams = screen.getByRole('option', { name: /williams/i });
    expect(williams).toHaveAttribute('aria-disabled', 'true');

    await user.keyboard('{ArrowDown}{Enter}');

    expect(screen.getByRole('listbox')).toBeInTheDocument();
    expect(getCombobox()).toHaveValue('wil');
    expect(screen.queryByRole('button', { name: /clear selection/i })).not.toBeInTheDocument();
  });

  it('shows the empty-options message (not "No matches") when there are no options at all', async () => {
    const user = userEvent.setup();
    render(SearchableSelect, {
      options: [],
      label: 'Manufacturer',
      placeholder: 'Search manufacturers...',
      selected: null,
      emptyMessage: 'No manufacturers match your other filters',
    });

    await user.click(getCombobox());

    expect(screen.getByText('No manufacturers match your other filters')).toBeInTheDocument();
    expect(screen.queryByText('No matches')).not.toBeInTheDocument();
  });

  it('shows "No matches" (not the empty-options message) when a query filters the list to empty', async () => {
    const user = userEvent.setup();
    render(SearchableSelect, {
      options: OPTIONS,
      label: 'Manufacturer',
      placeholder: 'Search manufacturers...',
      selected: null,
      emptyMessage: 'No manufacturers match your other filters',
    });

    await user.click(getCombobox());
    await user.type(getCombobox(), 'zzz-nothing-matches');

    expect(screen.getByText('No matches')).toBeInTheDocument();
    expect(screen.queryByText('No manufacturers match your other filters')).not.toBeInTheDocument();
  });

  it('portals the listbox out of clipping ancestors', async () => {
    const user = userEvent.setup();
    render(SearchableSelectClipFixture);

    await user.click(getCombobox());

    const listbox = screen.getByRole('listbox');
    const wrapper = screen.getByTestId('clip-wrapper');
    expect(wrapper).not.toContainElement(listbox);
  });

  it('syncs activeIndex with pointer hover so it does not conflict with keyboard nav', async () => {
    const user = userEvent.setup();
    renderSingle();

    await user.click(getCombobox());

    // Hover Bally — it should become the active option.
    const bally = screen.getByRole('option', { name: /bally/i });
    await fireEvent.pointerEnter(bally);

    expect(bally).toHaveAttribute('data-active', 'true');
    expect(getCombobox()).toHaveAttribute('aria-activedescendant', bally.id);

    // Keyboard-arrowing should move activity off Bally to exactly one other option.
    await user.keyboard('{ArrowDown}');
    expect(bally).toHaveAttribute('data-active', 'false');
    expect(document.querySelectorAll('[data-active="true"]')).toHaveLength(1);
  });

  it('closes when focus moves outside the component (e.g. Tab to next field)', async () => {
    const user = userEvent.setup();
    renderSingle();
    const after = document.createElement('button');
    after.id = 'after';
    after.textContent = 'After';
    document.body.appendChild(after);

    await user.click(getCombobox());
    expect(screen.getByRole('listbox')).toBeInTheDocument();

    after.focus();
    fireEvent.focusIn(after);

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('closes when clicking outside the portaled listbox', async () => {
    const user = userEvent.setup();
    render(SearchableSelectClipFixture);

    await user.click(getCombobox());
    expect(screen.getByRole('listbox')).toBeInTheDocument();

    fireEvent.pointerDown(document.body);

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('does not leave queued scroll work behind after keyboard navigation unmounts', async () => {
    vi.useFakeTimers();
    try {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      const rendered = renderSingle();

      await user.click(getCombobox());
      await user.keyboard('{ArrowDown}');

      rendered.unmount();

      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });
});
