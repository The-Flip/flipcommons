import { beforeEach, describe, expect, it, vi } from 'vitest';
import { loadAuthenticatedMe } from './load-me.server';

const GET = vi.fn();
const client = { GET } as unknown as Parameters<typeof loadAuthenticatedMe>[0];

function ok<T>(data: T, status = 200) {
  return { data, error: undefined, response: new Response(null, { status }) };
}

beforeEach(() => {
  GET.mockReset();
});

describe('loadAuthenticatedMe', () => {
  it('returns the parsed Me on success', async () => {
    GET.mockResolvedValueOnce(ok({ is_authenticated: true, capabilities: { 'x.y': true } }));
    const me = await loadAuthenticatedMe(client, 'test');
    expect(me.is_authenticated).toBe(true);
    expect(me.capabilities?.['x.y']).toBe(true);
  });

  it('redirects anonymous users to /login', async () => {
    GET.mockResolvedValueOnce(ok({ is_authenticated: false, capabilities: {} }));
    await expect(loadAuthenticatedMe(client, 'test')).rejects.toMatchObject({
      status: 302,
      location: '/login',
    });
  });

  // #420: the literal failure mode from the Sentry trace — DNS resolution
  // against the public origin fails from inside the container. The rejection
  // must propagate untouched so handleError logs it and Sentry captures it;
  // wrapping it in error() would silence both.
  it('propagates the rejection when the /me/ fetch fails (network failure)', async () => {
    const cause = new Error('getaddrinfo ENOTFOUND flipcommons.org');
    GET.mockRejectedValueOnce(cause);
    await expect(loadAuthenticatedMe(client, 'test')).rejects.toBe(cause);
  });

  it('throws a plain Error when /me/ returns non-2xx with no data', async () => {
    GET.mockResolvedValueOnce({
      data: undefined,
      error: { detail: 'nope' },
      response: new Response(null, { status: 502 }),
    });
    await expect(loadAuthenticatedMe(client, 'test')).rejects.toThrow(/returned 502/);
  });

  // openapi-fetch does not runtime-validate the generated schema. A 200
  // with a body that's missing is_authenticated (or has a non-boolean
  // value) is an upstream schema fault — must surface as a system error,
  // not get reinterpreted as anonymous and redirect to /login.
  it('throws a plain Error when /me/ body is missing is_authenticated', async () => {
    GET.mockResolvedValueOnce(ok({ capabilities: {} } as unknown as { is_authenticated: boolean }));
    await expect(loadAuthenticatedMe(client, 'test')).rejects.toThrow(/returned 200/);
  });

  it('throws a plain Error when /me/ body has non-boolean is_authenticated', async () => {
    GET.mockResolvedValueOnce(
      ok({ is_authenticated: 'true' } as unknown as { is_authenticated: boolean }),
    );
    await expect(loadAuthenticatedMe(client, 'test')).rejects.toThrow(/returned 200/);
  });

  // error() bypasses handleError, so a fault must never be thrown through it.
  it('never throws a SvelteKit HttpError for a fault', async () => {
    GET.mockResolvedValueOnce({
      data: undefined,
      error: undefined,
      response: new Response(null, { status: 204 }),
    });
    await expect(loadAuthenticatedMe(client, 'test')).rejects.not.toHaveProperty('status');
  });
});
