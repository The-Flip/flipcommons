import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ModelRelationshipSchema } from '$lib/api/schema';
import RelatedModelsEditorFixture from './RelatedModelsEditor.fixture.svelte';

const { GET, PATCH } = vi.hoisted(() => ({
  GET: vi.fn(),
  PATCH: vi.fn(),
}));

const { invalidateAll } = vi.hoisted(() => ({
  invalidateAll: vi.fn(),
}));

vi.mock('$lib/api/client', () => ({
  default: { GET, PATCH },
}));

vi.mock('$app/navigation', () => ({
  invalidateAll,
}));

// Rows the autocomplete endpoint returns, filtered by the typed query below.
// `medieval-madness` is the fixture's own model — it must be excluded.
const AUTOCOMPLETE_ROWS = [
  { value: 'medieval-madness', label: 'Medieval Madness', sublabel: null },
  { value: 'attack-from-mars', label: 'Attack from Mars', sublabel: 'Bally · 1995' },
  { value: 'monster-bash', label: 'Monster Bash', sublabel: null },
];

function mockResponses() {
  GET.mockImplementation(async (path: string, opts?: { params?: { query?: { q?: string } } }) => {
    if (path === '/api/entity-autocomplete/') {
      const q = (opts?.params?.query?.q ?? '').toLowerCase();
      const results = AUTOCOMPLETE_ROWS.filter((r) => r.label.toLowerCase().includes(q));
      return { data: { results }, error: undefined, response: { status: 200 } };
    }
    throw new Error(`Unexpected GET ${path}`);
  });
  PATCH.mockResolvedValue({ data: { slug: 'medieval-madness' }, error: undefined });
}

const CLEAN = { variant_of: null, remake_of: null, relationships: [] };

const BOOTLEG_EDGE: ModelRelationshipSchema = {
  relationship_type: 'copy',
  license_status: 'unlicensed',
  target_machine: {
    name: 'Galaxie',
    public_id: 'galaxie',
    year: 1971,
    manufacturer: { name: 'Gottlieb', public_id: 'gottlieb' },
  },
  target_label: '',
};

const KIT_EDGE: ModelRelationshipSchema = {
  relationship_type: 'conversion_kit',
  license_status: 'unknown',
  target_machine: null,
  target_label: 'several Gottlieb EM models',
};

function kindSelects(): HTMLSelectElement[] {
  return screen.getAllByRole('combobox', { name: 'Relationship kind' }) as HTMLSelectElement[];
}

async function pickTarget(
  user: ReturnType<typeof userEvent.setup>,
  optionName: RegExp,
): Promise<void> {
  await user.click(screen.getByPlaceholderText('Search models...'));
  await user.click(await screen.findByRole('option', { name: optionName }));
}

describe('RelatedModelsEditor', () => {
  beforeEach(() => {
    GET.mockReset();
    PATCH.mockReset();
    invalidateAll.mockReset();
    mockResponses();
  });

  it('renders saved rows as inline controls', () => {
    render(RelatedModelsEditorFixture, {
      props: { initialData: { ...CLEAN, relationships: [BOOTLEG_EDGE, KIT_EDGE] } },
    });

    const kinds = kindSelects();
    expect(kinds).toHaveLength(2);
    expect(kinds[0]).toHaveValue('copy');
    expect(kinds[1]).toHaveValue('conversion_kit');

    expect(screen.getByDisplayValue('Galaxie (Gottlieb 1971)')).toBeInTheDocument();
    expect(screen.getByDisplayValue('several Gottlieb EM models')).toBeInTheDocument();
    expect(screen.getAllByRole('combobox', { name: 'License status' })[0]).toHaveValue(
      'unlicensed',
    );
    expect(screen.getByTestId('dirty')).toHaveTextContent('false');
  });

  it('reveals the target only after a kind is chosen', async () => {
    const user = userEvent.setup();
    render(RelatedModelsEditorFixture, { props: { initialData: CLEAN } });

    await user.click(screen.getByRole('button', { name: 'Add relationship' }));
    // A fresh row shows just the kind dropdown — no target or license yet.
    expect(screen.queryByPlaceholderText('Search models...')).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: 'License status' })).not.toBeInTheDocument();

    await user.selectOptions(kindSelects()[0], 'copy');
    expect(screen.getByPlaceholderText('Search models...')).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'License status' })).toBeInTheDocument();
  });

  it('adds a machine-target edge inline and PATCHes it', async () => {
    const user = userEvent.setup();
    render(RelatedModelsEditorFixture, { props: { initialData: CLEAN } });

    await user.click(screen.getByRole('button', { name: 'Add relationship' }));
    // The new row starts unset — choose the kind, then pick a machine.
    await user.selectOptions(kindSelects()[0], 'copy');
    await pickTarget(user, /Attack from Mars/);
    await user.selectOptions(
      screen.getByRole('combobox', { name: 'License status' }),
      'unlicensed',
    );
    expect(screen.getByTestId('dirty')).toHaveTextContent('true');

    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(PATCH).toHaveBeenCalledTimes(1));
    expect(PATCH).toHaveBeenCalledWith(
      '/api/models/{public_id}/claims/',
      expect.objectContaining({
        body: expect.objectContaining({
          relationships: [
            {
              relationship_type: 'copy',
              license_status: 'unlicensed',
              target_slug: 'attack-from-mars',
              target_label: '',
            },
          ],
        }),
      }),
    );
  });

  it('adds a label-target edge via the describe-it toggle', async () => {
    const user = userEvent.setup();
    render(RelatedModelsEditorFixture, { props: { initialData: CLEAN } });

    await user.click(screen.getByRole('button', { name: 'Add relationship' }));
    await user.selectOptions(kindSelects()[0], 'conversion_kit');
    await user.click(
      screen.getByRole('button', {
        name: 'Not in the catalog, or several machines? Describe it',
      }),
    );
    await user.type(
      screen.getByRole('textbox', { name: 'Describe the target' }),
      'several Gottlieb EM models',
    );

    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(PATCH).toHaveBeenCalledTimes(1));
    expect(PATCH).toHaveBeenCalledWith(
      '/api/models/{public_id}/claims/',
      expect.objectContaining({
        body: expect.objectContaining({
          relationships: [
            {
              relationship_type: 'conversion_kit',
              license_status: 'unknown',
              target_slug: '',
              target_label: 'several Gottlieb EM models',
            },
          ],
        }),
      }),
    );
  });

  it('removes a saved row and drops it from the save payload', async () => {
    const user = userEvent.setup();
    render(RelatedModelsEditorFixture, {
      props: { initialData: { ...CLEAN, relationships: [BOOTLEG_EDGE, KIT_EDGE] } },
    });

    const removeButtons = screen.getAllByRole('button', { name: 'Remove relationship' });
    await user.click(removeButtons[0]); // drop the Galaxie copy
    expect(screen.queryByDisplayValue('Galaxie (Gottlieb 1971)')).not.toBeInTheDocument();
    expect(screen.getByTestId('dirty')).toHaveTextContent('true');

    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(PATCH).toHaveBeenCalledTimes(1));
    expect(PATCH).toHaveBeenCalledWith(
      '/api/models/{public_id}/claims/',
      expect.objectContaining({
        body: expect.objectContaining({
          relationships: [
            {
              relationship_type: 'conversion_kit',
              license_status: 'unknown',
              target_slug: '',
              target_label: 'several Gottlieb EM models',
            },
          ],
        }),
      }),
    );
  });

  it('edits a license in place and marks the section dirty', async () => {
    const user = userEvent.setup();
    render(RelatedModelsEditorFixture, {
      props: { initialData: { ...CLEAN, relationships: [BOOTLEG_EDGE] } },
    });

    expect(screen.getByTestId('dirty')).toHaveTextContent('false');
    await user.selectOptions(screen.getByRole('combobox', { name: 'License status' }), 'licensed');
    expect(screen.getByTestId('dirty')).toHaveTextContent('true');

    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(PATCH).toHaveBeenCalledTimes(1));
    expect(PATCH).toHaveBeenCalledWith(
      '/api/models/{public_id}/claims/',
      expect.objectContaining({
        body: expect.objectContaining({
          relationships: [
            expect.objectContaining({ license_status: 'licensed', target_slug: 'galaxie' }),
          ],
        }),
      }),
    );
  });

  it('sets variant_of as a scalar field, not an edge', async () => {
    const user = userEvent.setup();
    render(RelatedModelsEditorFixture, { props: { initialData: CLEAN } });

    await user.click(screen.getByRole('button', { name: 'Add relationship' }));
    await user.selectOptions(kindSelects()[0], 'variant');
    // Variant has no license selector — the target picker is the whole row.
    expect(screen.queryByRole('combobox', { name: 'License status' })).not.toBeInTheDocument();
    await pickTarget(user, /Attack from Mars/);

    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(PATCH).toHaveBeenCalledTimes(1));
    expect(PATCH).toHaveBeenCalledWith(
      '/api/models/{public_id}/claims/',
      expect.objectContaining({
        body: expect.objectContaining({ fields: { variant_of: 'attack-from-mars' } }),
      }),
    );
    const body = PATCH.mock.calls[0][1].body;
    expect(body.relationships).toBeUndefined();
  });

  it('disables the variant option once a variant row exists', async () => {
    const user = userEvent.setup();
    render(RelatedModelsEditorFixture, {
      props: {
        initialData: {
          ...CLEAN,
          variant_of: { public_id: 'attack-from-mars', name: 'Attack from Mars' },
        },
      },
    });

    // Add a second row; its kind menu can't offer Variant again.
    await user.click(screen.getByRole('button', { name: 'Add relationship' }));
    const secondRowVariantOption = screen
      .getAllByRole('option', { name: 'Variant of' })
      .at(-1) as HTMLOptionElement;
    expect(secondRowVariantOption).toBeDisabled();
  });

  it('excludes the current model from target options', async () => {
    const user = userEvent.setup();
    render(RelatedModelsEditorFixture, { props: { initialData: CLEAN } });

    await user.click(screen.getByRole('button', { name: 'Add relationship' }));
    // The target picker only appears once a kind is chosen.
    await user.selectOptions(kindSelects()[0], 'copy');
    await user.click(screen.getByPlaceholderText('Search models...'));

    expect(await screen.findByRole('option', { name: /Attack from Mars/ })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Medieval Madness' })).not.toBeInTheDocument();
  });

  it('rejects the same machine under two kinds before PATCHing', async () => {
    // The claim identity is the target alone — the same machine under two
    // kinds would collide on one edge, so the save is blocked client-side.
    const user = userEvent.setup();
    render(RelatedModelsEditorFixture, { props: { initialData: CLEAN } });

    await user.click(screen.getByRole('button', { name: 'Add relationship' }));
    await user.selectOptions(kindSelects()[0], 'copy');
    await pickTarget(user, /Attack from Mars/);

    await user.click(screen.getByRole('button', { name: 'Add relationship' }));
    await user.selectOptions(kindSelects()[1], 'conversion');
    // Two rows → two search inputs; drive the second row's picker.
    await user.click(screen.getAllByPlaceholderText('Search models...')[1]);
    await user.click(await screen.findByRole('option', { name: /Attack from Mars/ }));

    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(PATCH).not.toHaveBeenCalled();
    expect(screen.getByTestId('last-error')).toHaveTextContent(
      'Two relationships have the same target.',
    );
  });

  it('disables the describe-it toggle while a label row exists', async () => {
    // A model holds one label slot; a second row can't switch to label mode.
    const user = userEvent.setup();
    render(RelatedModelsEditorFixture, {
      props: { initialData: { ...CLEAN, relationships: [KIT_EDGE] } },
    });

    await user.click(screen.getByRole('button', { name: 'Add relationship' }));
    await user.selectOptions(kindSelects().at(-1) as HTMLSelectElement, 'copy');
    expect(
      screen.getByRole('button', {
        name: 'Not in the catalog, or several machines? Describe it',
      }),
    ).toBeDisabled();
  });

  it('re-enables the describe-it toggle when the label row is removed', async () => {
    const user = userEvent.setup();
    render(RelatedModelsEditorFixture, {
      props: { initialData: { ...CLEAN, relationships: [KIT_EDGE] } },
    });

    await user.click(screen.getByRole('button', { name: 'Add relationship' }));
    await user.selectOptions(kindSelects().at(-1) as HTMLSelectElement, 'copy');

    // Removing the existing label row frees the slot for the new row.
    await user.click(screen.getAllByRole('button', { name: 'Remove relationship' })[0]);
    expect(
      screen.getByRole('button', {
        name: 'Not in the catalog, or several machines? Describe it',
      }),
    ).toBeEnabled();
  });

  it('disables Add until the new row has a kind and a target', async () => {
    const user = userEvent.setup();
    render(RelatedModelsEditorFixture, { props: { initialData: CLEAN } });

    const addButton = screen.getByRole('button', { name: 'Add relationship' });
    await user.click(addButton);
    expect(addButton).toBeDisabled();

    // A target alone isn't enough — the kind still reads "Choose relationship…".
    await user.selectOptions(kindSelects()[0], 'copy');
    expect(addButton).toBeDisabled();

    await pickTarget(user, /Attack from Mars/);
    expect(addButton).toBeEnabled();
  });
});
