import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import CreatePage from './CreatePage.svelte';
import { validationErrorBody } from '$lib/api/error-fixtures';
import { toast } from '$lib/toast/toast.svelte';

const { goto, resolve } = vi.hoisted(() => ({
  goto: vi.fn(),
  resolve: vi.fn((url: string) => url),
}));

vi.mock('$app/navigation', () => ({ goto }));
vi.mock('$app/paths', () => ({ resolve }));

type Created = { slug: string; name: string };
type Submit = (body: {
  name: string;
  slug: string;
  note: string;
  citation: unknown;
}) => Promise<{ data: Created | undefined; error: unknown; response: Response }>;

type Overrides = {
  entityLabel?: string;
  heading?: string;
  initialName?: string;
  submit?: Submit;
  detailHref?: (slug: string) => string;
  cancelHref?: string;
  parentBreadcrumb?: { text: string; href: string };
  projectSlug?: (name: string) => string;
  notePlaceholder?: string;
};

function makeResponse(status: number, headers: Record<string, string> = {}): Response {
  return {
    status,
    headers: new Headers(headers),
  } as Response;
}

function okSubmit(slug: string, name: string): Submit {
  return vi.fn().mockResolvedValue({
    data: { slug, name },
    error: undefined,
    response: makeResponse(201),
  });
}

function renderDefault(overrides: Overrides = {}) {
  const submit = overrides.submit ?? okSubmit('ada-lovelace', 'Ada Lovelace');
  render(CreatePage<Created>, {
    entityLabel: 'Person',
    initialName: 'Ada Lovelace',
    submit,
    detailHref: (slug: string) => `/people/${slug}`,
    cancelHref: '/people',
    ...overrides,
  });
  return { submit };
}

describe('CreatePage', () => {
  beforeEach(() => {
    goto.mockReset();
    goto.mockResolvedValue(undefined);
    resolve.mockClear();
    toast._resetForTest();
  });

  afterEach(() => {
    toast._resetForTest();
  });

  it('renders default heading and prefilled name/slug from initialName', () => {
    renderDefault();
    expect(screen.getByRole('heading', { name: 'New Person' })).toBeInTheDocument();
    expect(screen.getByLabelText('Name')).toHaveValue('Ada Lovelace');
    expect(screen.getByLabelText('Slug')).toHaveValue('ada-lovelace');
  });

  it('uses heading override when supplied', () => {
    renderDefault({ heading: 'New model in Attack from Mars' });
    expect(
      screen.getByRole('heading', { name: 'New model in Attack from Mars' }),
    ).toBeInTheDocument();
  });

  it('renders parentBreadcrumb link when supplied', () => {
    renderDefault({
      parentBreadcrumb: { text: 'Attack from Mars', href: '/titles/attack-from-mars' },
    });
    const link = screen.getByRole('link', { name: 'Attack from Mars' });
    expect(link).toHaveAttribute('href', '/titles/attack-from-mars');
  });

  it('does not render a parent breadcrumb when prop is omitted', () => {
    renderDefault();
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
    expect(screen.queryAllByRole('link')).toHaveLength(0);
  });

  it('auto-syncs slug from name until user diverges slug', async () => {
    const user = userEvent.setup();
    renderDefault({ initialName: '' });

    const nameInput = screen.getByLabelText('Name') as HTMLInputElement;
    const slugInput = screen.getByLabelText('Slug') as HTMLInputElement;

    await user.type(nameInput, 'Grace Hopper');
    expect(slugInput.value).toBe('grace-hopper');

    // Diverge the slug manually; sync should stop.
    await user.clear(slugInput);
    await user.type(slugInput, 'grace-h');
    await user.type(nameInput, 'x');
    expect(slugInput.value).toBe('grace-h');
  });

  it('uses a custom projectSlug for the initial slug and for sync', async () => {
    const user = userEvent.setup();
    const projectSlug = vi.fn((name: string) => `mm-${name.toLowerCase().replace(/\s+/g, '-')}`);
    renderDefault({ initialName: 'Pro', projectSlug });

    const slugInput = screen.getByLabelText('Slug') as HTMLInputElement;
    expect(slugInput.value).toBe('mm-pro');

    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'Premium');
    expect(slugInput.value).toBe('mm-premium');
  });

  it('submit receives a trimmed, well-formed body including built citation', async () => {
    const user = userEvent.setup();
    const submit = okSubmit('ada-lovelace', 'Ada Lovelace');
    renderDefault({ submit });

    // Add leading whitespace to verify trimming.
    const nameInput = screen.getByLabelText('Name') as HTMLInputElement;
    await user.clear(nameInput);
    await user.type(nameInput, '  Ada Lovelace  ');

    await user.click(screen.getByRole('button', { name: 'Create Person' }));

    expect(submit).toHaveBeenCalledTimes(1);
    expect(submit).toHaveBeenCalledWith({
      name: 'Ada Lovelace',
      slug: 'ada-lovelace',
      note: '',
      citation: undefined,
    });
  });

  it('ok outcome: shows success toast and navigates via detailHref', async () => {
    const user = userEvent.setup();
    const submit = okSubmit('ada-lovelace', 'Ada Lovelace');
    renderDefault({ submit });

    await user.click(screen.getByRole('button', { name: 'Create Person' }));

    expect(toast.messages).toHaveLength(1);
    expect(toast.messages[0].text).toContain('Created');
    expect(toast.messages[0].text).toContain('Ada Lovelace');
    expect(toast.messages[0].persistUntilNav).toBe(true);
    expect(resolve).toHaveBeenCalledWith('/people/ada-lovelace');
    expect(goto).toHaveBeenCalledWith('/people/ada-lovelace');
  });

  it('rate_limited outcome (429): shows form error, no toast, no navigation', async () => {
    const user = userEvent.setup();
    const submit = vi.fn().mockResolvedValue({
      data: undefined,
      error: { detail: 'Too many' },
      response: makeResponse(429, { 'Retry-After': '3600' }),
    });
    renderDefault({ submit });

    await user.click(screen.getByRole('button', { name: 'Create Person' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/create limit/i);
    expect(toast.messages).toHaveLength(0);
    expect(goto).not.toHaveBeenCalled();
  });

  it('field_errors outcome: attributes errors to name/slug fields', async () => {
    const user = userEvent.setup();
    const submit = vi.fn().mockResolvedValue({
      data: undefined,
      error: {
        detail: validationErrorBody({
          message: 'Validation failed.',
          field_errors: {
            name: 'Name already exists.',
            slug: 'Slug already taken.',
          },
        }),
      },
      response: makeResponse(422),
    });
    renderDefault({ submit });

    await user.click(screen.getByRole('button', { name: 'Create Person' }));

    expect(await screen.findByText('Name already exists.')).toBeInTheDocument();
    expect(screen.getByText('Slug already taken.')).toBeInTheDocument();
    expect(toast.messages).toHaveLength(0);
    expect(goto).not.toHaveBeenCalled();
  });

  it('form_error outcome: shows generic error alert', async () => {
    const user = userEvent.setup();
    const submit = vi.fn().mockResolvedValue({
      data: undefined,
      error: { detail: 'Server exploded.' },
      response: makeResponse(500),
    });
    renderDefault({ submit });

    await user.click(screen.getByRole('button', { name: 'Create Person' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toBeInTheDocument();
    expect(toast.messages).toHaveLength(0);
    expect(goto).not.toHaveBeenCalled();
  });

  it('blank name: does not call submit, shows a field error', async () => {
    const user = userEvent.setup();
    const submit = vi.fn();
    renderDefault({ initialName: '', submit });

    await user.click(screen.getByRole('button', { name: 'Create Person' }));

    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByText('Name cannot be blank.')).toBeInTheDocument();
  });

  it('Cancel button resolves and navigates to cancelHref', async () => {
    const user = userEvent.setup();
    renderDefault();

    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(resolve).toHaveBeenCalledWith('/people');
    expect(goto).toHaveBeenCalledWith('/people');
  });
});

describe('CreatePage extras', () => {
  beforeEach(() => {
    goto.mockReset();
    goto.mockResolvedValue(undefined);
    resolve.mockClear();
    toast._resetForTest();
  });

  afterEach(() => {
    toast._resetForTest();
  });

  it('merges extraBody output into the submit body', async () => {
    const user = userEvent.setup();
    const submit = vi.fn().mockResolvedValue({
      data: { slug: 'ada-lovelace', name: 'Ada Lovelace' },
      error: undefined,
      response: makeResponse(201),
    });

    const ExtrasFixture = (await import('./CreatePage.extras.fixture.svelte')).default;
    render(ExtrasFixture, { extraValue: 'stern', submit });

    await user.click(screen.getByRole('button', { name: 'Create System' }));

    expect(submit).toHaveBeenCalledOnce();
    const body = submit.mock.calls[0]?.[0];
    expect(body).toMatchObject({
      name: 'Ada',
      slug: 'ada',
      manufacturer_slug: 'stern',
    });
  });

  it('extraBody {error} blocks submission with a form-level error', async () => {
    const user = userEvent.setup();
    const submit = vi.fn();

    const ExtrasFixture = (await import('./CreatePage.extras.fixture.svelte')).default;
    render(ExtrasFixture, {
      extraError: 'Manufacturer is required.',
      submit,
    });

    await user.click(screen.getByRole('button', { name: 'Create System' }));

    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('Manufacturer is required.');
  });

  it('server field_errors route to extraFieldKeys instead of formError', async () => {
    const user = userEvent.setup();
    const submit = vi.fn().mockResolvedValue({
      data: undefined,
      error: {
        detail: validationErrorBody({
          message: 'Validation failed.',
          field_errors: { manufacturer_slug: 'Manufacturer not found.' },
        }),
      },
      response: makeResponse(422),
    });

    const ExtrasFixture = (await import('./CreatePage.extras.fixture.svelte')).default;
    render(ExtrasFixture, { extraValue: 'stern', submit });

    await user.click(screen.getByRole('button', { name: 'Create System' }));

    expect(await screen.findByTestId('extra-error')).toHaveTextContent('Manufacturer not found.');
    // formError is NOT the generic fallback in this case
    expect(screen.queryByRole('alert')).toBeNull();
    expect(goto).not.toHaveBeenCalled();
  });
});
