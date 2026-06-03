import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { validationErrorBody } from '$lib/api/error-fixtures';

const { goto, resolve, mockPost } = vi.hoisted(() => ({
  goto: vi.fn(),
  resolve: vi.fn((url: string) => url),
  mockPost: vi.fn(),
}));

vi.mock('$app/navigation', () => ({ goto }));
vi.mock('$app/paths', () => ({ resolve }));
vi.mock('$lib/api/client', () => ({
  default: { POST: mockPost },
}));

vi.mock('$lib/components/editors/system-edit-options', () => ({
  fetchManufacturerOptions: () =>
    Promise.resolve([
      { value: 'stern', label: 'Stern', count: 42 },
      { value: 'williams', label: 'Williams', count: 9 },
    ]),
}));

import Page from './+page.svelte';
import { toast } from '$lib/toast/toast.svelte';

function renderPage(initialName = '') {
  render(Page, { data: { initialName } });
}

describe('systems/new route', () => {
  beforeEach(() => {
    goto.mockReset();
    goto.mockResolvedValue(undefined);
    resolve.mockClear();
    mockPost.mockReset();
    toast._resetForTest();
  });

  afterEach(() => {
    toast._resetForTest();
  });

  it('blocks submit when manufacturer is not selected', async () => {
    const user = userEvent.setup();
    renderPage('SPIKE');

    await user.click(screen.getByRole('button', { name: 'Create System' }));

    expect(mockPost).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('Manufacturer is required.');
  });

  it('routes server field errors for manufacturer_slug to the picker', async () => {
    const user = userEvent.setup();
    mockPost.mockResolvedValue({
      data: undefined,
      error: {
        detail: validationErrorBody({
          message: 'Validation failed.',
          field_errors: { manufacturer_slug: 'Manufacturer not found.' },
        }),
      },
      response: { status: 422, headers: new Headers() } as Response,
    });

    renderPage('SPIKE');

    // Select Stern via the SearchableSelect input.
    const search = screen.getByPlaceholderText('Search manufacturers...');
    await user.click(search);
    await user.click(await screen.findByRole('option', { name: /Stern/ }));

    await user.click(screen.getByRole('button', { name: 'Create System' }));

    // Body carries the extra field...
    expect(mockPost).toHaveBeenCalledOnce();
    const [path, init] = mockPost.mock.calls[0];
    expect(path).toBe('/api/systems/');
    expect(init.body).toMatchObject({
      name: 'SPIKE',
      slug: 'spike',
      manufacturer_slug: 'stern',
    });

    // ...and the server's field error renders at the picker, not as a
    // generic form alert. Both the form-level alert and the field error
    // use role="alert", so we have to disambiguate by class: the form
    // alert is CreatePage's `.save-error`. If CreatePage regressed to
    // dumping extra-key field errors into formError, that save-error
    // node would appear.
    expect(await screen.findByText('Manufacturer not found.')).toBeInTheDocument();
    expect(document.querySelector('.save-error')).toBeNull();
    expect(goto).not.toHaveBeenCalled();
  });
});
