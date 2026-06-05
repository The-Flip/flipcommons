import { fireEvent, render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { EntityOption } from '$lib/api/entity-autocomplete';

const DATA: EntityOption[] = [
  { value: 'action', label: 'Action', sublabel: null },
  { value: 'horror', label: 'Horror', sublabel: null },
  { value: 'scifi', label: 'Sci-Fi', sublabel: null },
];

const autocompleteEntities = vi.fn((_type: string, q: string) =>
  Promise.resolve(DATA.filter((d) => d.label.toLowerCase().includes(q.toLowerCase()))),
);

// Partial mock: stub only the network call; keep the real AUTOCOMPLETE_RESULT_LIMIT.
vi.mock('$lib/api/entity-autocomplete', async (importOriginal) => ({
  ...(await importOriginal<typeof import('$lib/api/entity-autocomplete')>()),
  autocompleteEntities: (type: string, q: string) => autocompleteEntities(type, q),
}));

const { default: EntityMultiSelect } = await import('./EntityMultiSelect.svelte');

function getCombobox() {
  return screen.getByRole('combobox', { name: /themes/i });
}

function renderMulti(props: Record<string, unknown> = {}) {
  return render(EntityMultiSelect, {
    type: 'theme',
    label: 'Themes',
    placeholder: 'Search themes...',
    ...props,
  });
}

beforeEach(() => {
  autocompleteEntities.mockClear();
});

describe('EntityMultiSelect', () => {
  it('renders chips from the initial selections with no search', () => {
    renderMulti({ selected: ['action', 'horror'], initialSelections: [DATA[0], DATA[1]] });

    expect(screen.getByText('Action')).toBeInTheDocument();
    expect(screen.getByText('Horror')).toBeInTheDocument();
    expect(autocompleteEntities).not.toHaveBeenCalled();
  });

  it('adds a chip when a row is selected and keeps the listbox open', async () => {
    const user = userEvent.setup();
    renderMulti({ selected: [] });

    await user.click(getCombobox());
    const option = await screen.findByRole('option', { name: /horror/i });
    await fireEvent.pointerDown(option);

    // Stays open for further multi-selection; the chip and the row's check both appear.
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /remove horror/i })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /horror/i })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });

  it('removes a chip with its remove button', async () => {
    const user = userEvent.setup();
    renderMulti({ selected: ['action', 'horror'], initialSelections: [DATA[0], DATA[1]] });

    await user.click(screen.getByRole('button', { name: /remove horror/i }));

    expect(screen.queryByText('Horror')).not.toBeInTheDocument();
    expect(screen.getByText('Action')).toBeInTheDocument();
  });

  it('keeps the input empty while a single chip speaks for the selection', () => {
    renderMulti({ selected: ['action'], initialSelections: [DATA[0]] });

    expect(getCombobox()).toHaveValue('');
    expect(screen.getByText('Action')).toBeInTheDocument();
  });

  it('summarizes the input when more than one value is selected', () => {
    renderMulti({ selected: ['action', 'horror'], initialSelections: [DATA[0], DATA[1]] });

    expect(getCombobox()).toHaveValue('2 selected');
  });

  it('marks already-selected rows with a check', async () => {
    const user = userEvent.setup();
    renderMulti({ selected: ['action'], initialSelections: [DATA[0]] });

    await user.click(getCombobox());
    const option = await screen.findByRole('option', { name: /action/i });
    expect(option).toHaveAttribute('aria-selected', 'true');
  });

  it('disables the chip remove buttons when disabled', () => {
    renderMulti({
      selected: ['action', 'horror'],
      initialSelections: [DATA[0], DATA[1]],
      disabled: true,
    });

    expect(screen.getByRole('button', { name: /remove action/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /remove horror/i })).toBeDisabled();
  });
});
