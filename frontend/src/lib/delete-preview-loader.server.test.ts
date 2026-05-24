import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const GET = vi.fn();
const createServerClient = vi.fn(() => ({ GET }));

vi.mock('$lib/api/server', () => ({ createServerClient }));

const { loadDeletePreview } = await import('./delete-preview-loader.server');

function ok<T>(data: T, status = 200) {
  return { data, error: undefined, response: new Response(null, { status }) };
}

function fail(status: number) {
  return {
    data: undefined,
    error: { detail: 'nope' },
    response: new Response(null, { status }),
  };
}

const fetchStub = (() => undefined) as unknown as typeof globalThis.fetch;
const url = new URL('http://localhost/themes/x/delete');
const request = new Request('http://localhost/themes/x/delete');

function args(overrides: Partial<Parameters<typeof loadDeletePreview>[0]> = {}) {
  return {
    fetch: fetchStub,
    url,
    request,
    public_id: 'cosmic',
    entity: 'themes' as const,
    notFoundRedirect: '/themes',
    ...overrides,
  };
}

beforeEach(() => {
  GET.mockReset();
  createServerClient.mockClear();
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

const capableMe = ok({ is_authenticated: true, capabilities: { 'catalog.delete': true } });

describe('loadDeletePreview', () => {
  // #420: must forward `request` so /me/ sees the user's cookie over SSR.
  it('forwards (fetch, url, request) to createServerClient', async () => {
    GET.mockResolvedValueOnce(capableMe).mockResolvedValueOnce(ok({}));
    await loadDeletePreview(args());
    expect(createServerClient).toHaveBeenCalledWith(fetchStub, url, request);
  });

  it('returns the preview body and public_id on success', async () => {
    const preview = { name: 'Theme', changeset_count: 3 };
    GET.mockResolvedValueOnce(capableMe).mockResolvedValueOnce(ok(preview));

    const result = await loadDeletePreview(args());

    expect(result).toEqual({ preview, public_id: 'cosmic' });
    expect(GET).toHaveBeenNthCalledWith(1, '/api/auth/me/');
    expect(GET).toHaveBeenNthCalledWith(2, '/api/themes/{public_id}/delete-preview/', {
      params: { path: { public_id: 'cosmic' } },
    });
  });

  it('redirects anonymous users to /login (via shared auth helper)', async () => {
    GET.mockResolvedValueOnce(ok({ is_authenticated: false, capabilities: {} }));

    await expect(loadDeletePreview(args())).rejects.toMatchObject({
      status: 302,
      location: '/login',
    });
  });

  it('redirects authenticated-but-uncapable users to /verify-email', async () => {
    GET.mockResolvedValueOnce(
      ok({ is_authenticated: true, capabilities: { 'catalog.delete': false } }),
    );

    await expect(loadDeletePreview(args())).rejects.toMatchObject({
      status: 302,
      location: '/verify-email',
    });
  });

  it('redirects to the fallback URL on 404', async () => {
    GET.mockResolvedValueOnce(capableMe).mockResolvedValueOnce(fail(404));

    await expect(loadDeletePreview(args({ public_id: 'missing' }))).rejects.toMatchObject({
      status: 302,
      location: '/themes',
    });
  });

  it('throws on other non-OK responses', async () => {
    GET.mockResolvedValueOnce(capableMe).mockResolvedValueOnce(fail(500));

    await expect(loadDeletePreview(args())).rejects.toThrow(/500/);
  });
});
