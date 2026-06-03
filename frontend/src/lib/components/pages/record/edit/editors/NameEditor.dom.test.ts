import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import NameEditorFixture from './NameEditor.fixture.svelte';

const { goto } = vi.hoisted(() => ({
  goto: vi.fn(),
}));

const { pageState } = vi.hoisted(() => ({
  pageState: {
    params: { slug: 'williams' },
    url: new URL('http://localhost:5173/manufacturers/williams?edit=name'),
  },
}));

vi.mock('$app/navigation', () => ({
  goto,
  invalidateAll: vi.fn(),
}));

vi.mock('$app/state', () => ({
  page: pageState,
}));

describe('NameEditor', () => {
  beforeEach(() => {
    goto.mockReset();
    pageState.params.slug = 'williams';
    pageState.url = new URL('http://localhost:5173/manufacturers/williams?edit=name');
  });

  it('reports clean state initially and dirty state after editing', async () => {
    const user = userEvent.setup();
    render(NameEditorFixture);

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('false');

    await user.click(screen.getByRole('button', { name: 'Check dirty' }));
    expect(screen.getByTestId('dirty-handle')).toHaveTextContent('false');

    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'Bally');

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('true');

    await user.click(screen.getByRole('button', { name: 'Check dirty' }));
    expect(screen.getByTestId('dirty-handle')).toHaveTextContent('true');
  });

  it('auto-suggests a slug as the user types a name', async () => {
    const user = userEvent.setup();
    render(NameEditorFixture);

    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'Bally');

    expect(screen.getByLabelText('Slug')).toHaveValue('bally');
  });

  it('calls the injected save function with only the changed fields', async () => {
    const user = userEvent.setup();
    render(NameEditorFixture);

    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'Bally');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByTestId('last-save-body')).toHaveTextContent(
      JSON.stringify({ fields: { name: 'Bally', slug: 'bally' } }),
    );
    expect(screen.getByTestId('saved-count')).toHaveTextContent('1');
  });

  it('skips the save call when clean', async () => {
    const user = userEvent.setup();
    render(NameEditorFixture);

    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByTestId('last-save-body')).toHaveTextContent('null');
    expect(screen.getByTestId('saved-count')).toHaveTextContent('1');
  });

  it('redirects to the renamed slug after a successful save', async () => {
    const user = userEvent.setup();
    render(NameEditorFixture, {
      props: { saveResult: { ok: true, updatedSlug: 'bally' } },
    });

    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'Bally');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(goto).toHaveBeenCalledWith('/manufacturers/bally?edit=name', { replaceState: true });
    expect(screen.getByTestId('saved-count')).toHaveTextContent('1');
  });

  it('redirects safely when the slug is a substring of the resource path segment', async () => {
    // Regression: plain string replace on `/peopl` would corrupt `/people/peopl/edit`
    // to `/bobe/peopl/edit` by matching the leading `/peopl` inside `/people`.
    pageState.url = new URL('http://localhost:5173/people/peopl/edit/name');
    const user = userEvent.setup();
    render(NameEditorFixture, {
      props: {
        initialData: { name: 'Peopl', slug: 'peopl' },
        slug: 'peopl',
        saveResult: { ok: true, updatedSlug: 'bob' },
      },
    });

    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'Bob');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(goto).toHaveBeenCalledWith('/people/bob/edit/name', { replaceState: true });
  });

  it('redirects safely when the slug equals the collection segment', async () => {
    // Regression: a regex anchored only on the trailing boundary would match the
    // leading `/people` collection segment first, producing `/bob/people/edit/name`.
    pageState.url = new URL('http://localhost:5173/people/people/edit/name');
    const user = userEvent.setup();
    render(NameEditorFixture, {
      props: {
        initialData: { name: 'People', slug: 'people' },
        slug: 'people',
        saveResult: { ok: true, updatedSlug: 'bob' },
      },
    });

    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'Bob');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(goto).toHaveBeenCalledWith('/people/bob/edit/name', { replaceState: true });
  });

  it('hides the abbreviations field when initialAbbreviations is not passed', () => {
    render(NameEditorFixture);
    expect(screen.queryByLabelText('Abbreviations')).toBeNull();
  });

  it('shows abbreviations and reports dirty when the tag set changes', async () => {
    const user = userEvent.setup();
    render(NameEditorFixture, {
      props: { initialAbbreviations: ['WMS'] },
    });

    expect(screen.getByLabelText('Abbreviations')).toBeInTheDocument();
    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('false');

    await user.type(screen.getByLabelText('Abbreviations'), 'BLY{Enter}');
    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('true');
  });

  it('sends only abbreviations in the save body when only abbreviations changed', async () => {
    const user = userEvent.setup();
    render(NameEditorFixture, {
      props: { initialAbbreviations: ['WMS'] },
    });

    await user.type(screen.getByLabelText('Abbreviations'), 'BLY{Enter}');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByTestId('last-save-body')).toHaveTextContent(
      JSON.stringify({ abbreviations: ['WMS', 'BLY'] }),
    );
  });

  it('sends both fields and abbreviations when both changed', async () => {
    const user = userEvent.setup();
    render(NameEditorFixture, {
      props: { initialAbbreviations: ['WMS'] },
    });

    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'Bally');
    await user.type(screen.getByLabelText('Abbreviations'), 'BLY{Enter}');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByTestId('last-save-body')).toHaveTextContent(
      JSON.stringify({ fields: { name: 'Bally', slug: 'bally' }, abbreviations: ['WMS', 'BLY'] }),
    );
  });

  it('surfaces field errors from the save result', async () => {
    const user = userEvent.setup();
    render(NameEditorFixture, {
      props: {
        saveResult: {
          ok: false,
          error: 'boom',
          fieldErrors: { name: 'already taken' },
        },
      },
    });

    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'Bally');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByTestId('last-error')).toHaveTextContent('Please fix the errors below.');
  });
});
