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

async function addEdgeViaForm(
  user: ReturnType<typeof userEvent.setup>,
  kindCard: RegExp,
): Promise<void> {
  await user.click(screen.getByRole('button', { name: 'Add relationship' }));
  await user.click(screen.getByRole('button', { name: kindCard }));
}

describe('RelatedModelsEditor', () => {
  beforeEach(() => {
    GET.mockReset();
    PATCH.mockReset();
    invalidateAll.mockReset();
    mockResponses();
  });

  it('renders saved rows as reader-facing phrases', () => {
    render(RelatedModelsEditorFixture, {
      props: { initialData: { ...CLEAN, relationships: [BOOTLEG_EDGE, KIT_EDGE] } },
    });

    expect(screen.getByText('Bootleg of Galaxie (Gottlieb 1971)')).toBeInTheDocument();
    expect(screen.getByText('Conversion kit for several Gottlieb EM models')).toBeInTheDocument();
    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('false');
  });

  it('adds a machine-target edge through picker → form and PATCHes it', async () => {
    const user = userEvent.setup();
    render(RelatedModelsEditorFixture, { props: { initialData: CLEAN } });

    await addEdgeViaForm(user, /^Copy /);
    await user.click(screen.getByRole('combobox', { name: 'Target machine' }));
    await user.click(await screen.findByRole('option', { name: /Attack from Mars/ }));
    await user.selectOptions(
      screen.getByRole('combobox', { name: 'License status' }),
      'unlicensed',
    );
    await user.click(screen.getByRole('button', { name: 'Add' }));

    // Back on the list: the pending row shows the phrase and the New chip.
    expect(screen.getByText(/Bootleg of Attack from Mars/)).toBeInTheDocument();
    expect(screen.getByText('New')).toBeInTheDocument();
    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('true');

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

    await addEdgeViaForm(user, /^Conversion kit /);
    await user.click(
      screen.getByRole('button', {
        name: 'Machine not in the catalog, or several machines? Describe it instead',
      }),
    );
    await user.type(
      screen.getByRole('textbox', { name: 'Describe the target' }),
      'several Gottlieb EM models',
    );
    await user.click(screen.getByRole('button', { name: 'Add' }));

    expect(screen.getByText('Conversion kit for several Gottlieb EM models')).toBeInTheDocument();

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

  it('marks a saved row removed with undo, and drops it from the save payload', async () => {
    const user = userEvent.setup();
    render(RelatedModelsEditorFixture, {
      props: { initialData: { ...CLEAN, relationships: [BOOTLEG_EDGE, KIT_EDGE] } },
    });

    await user.click(screen.getByRole('button', { name: /Remove Bootleg of Galaxie/ }));
    // The struck-through row stays visible with an Undo, and the state is dirty.
    expect(screen.getByText('Bootleg of Galaxie (Gottlieb 1971)')).toBeInTheDocument();
    expect(screen.getByText('Removed')).toBeInTheDocument();
    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('true');

    await user.click(screen.getByRole('button', { name: 'Undo' }));
    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('false');

    await user.click(screen.getByRole('button', { name: /Remove Bootleg of Galaxie/ }));
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

  it('edits a row in place and marks it Changed', async () => {
    const user = userEvent.setup();
    render(RelatedModelsEditorFixture, {
      props: { initialData: { ...CLEAN, relationships: [BOOTLEG_EDGE] } },
    });

    await user.click(screen.getByText('Bootleg of Galaxie (Gottlieb 1971)'));
    // The form reopens pre-populated — switch the license without re-picking.
    await user.selectOptions(screen.getByRole('combobox', { name: 'License status' }), 'licensed');
    await user.click(screen.getByRole('button', { name: 'Update' }));

    expect(screen.getByText('Licensed copy of Galaxie (Gottlieb 1971)')).toBeInTheDocument();
    expect(screen.getByText('Changed')).toBeInTheDocument();
    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('true');
  });

  it('sets variant_of through the unified flow as a scalar field', async () => {
    const user = userEvent.setup();
    render(RelatedModelsEditorFixture, { props: { initialData: CLEAN } });

    await addEdgeViaForm(user, /^Variant /);
    // Variant has no license selector — the target picker is the whole form.
    expect(screen.queryByRole('combobox', { name: 'License status' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('combobox', { name: 'Target machine' }));
    await user.click(await screen.findByRole('option', { name: /Attack from Mars/ }));
    await user.click(screen.getByRole('button', { name: 'Add' }));

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

  it('disables the variant card when a variant row already exists', async () => {
    const user = userEvent.setup();
    render(RelatedModelsEditorFixture, {
      props: {
        initialData: {
          ...CLEAN,
          variant_of: { public_id: 'attack-from-mars', name: 'Attack from Mars' },
        },
      },
    });

    expect(screen.getByText('Variant of Attack from Mars')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Add relationship' }));
    expect(screen.getByRole('button', { name: /^Variant / })).toBeDisabled();
    expect(screen.getByRole('button', { name: /^Copy / })).toBeEnabled();
  });

  it('excludes the current model from target options', async () => {
    const user = userEvent.setup();
    render(RelatedModelsEditorFixture, { props: { initialData: CLEAN } });

    await addEdgeViaForm(user, /^Copy /);
    await user.click(screen.getByRole('combobox', { name: 'Target machine' }));

    expect(await screen.findByRole('option', { name: /Attack from Mars/ })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Medieval Madness' })).not.toBeInTheDocument();
  });

  it('rejects a form commit with no target', async () => {
    const user = userEvent.setup();
    render(RelatedModelsEditorFixture, { props: { initialData: CLEAN } });

    await addEdgeViaForm(user, /^Copy /);
    await user.click(screen.getByRole('button', { name: 'Add' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Select a target machine.');
    expect(PATCH).not.toHaveBeenCalled();
  });
});
