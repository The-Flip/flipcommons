import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createApiClient, registerOnPolicyDenied } from './create-client';

describe('createApiClient', () => {
  it('creates a server-safe client with explicit fetch', async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    const apiClient = createApiClient(fetch, 'http://localhost:5173');

    await apiClient.GET('/api/health');

    const request = fetch.mock.calls[0]?.[0];
    expect(request).toBeInstanceOf(Request);
    expect(request.url).toBe('http://localhost:5173/api/health');
  });

  describe('cookie forwarding for SSR', () => {
    it('forwards the Cookie header from the incoming request', async () => {
      const fetch = vi.fn().mockResolvedValue(
        new Response(JSON.stringify({}), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
      const incoming = new Request('https://flipcommons.org/kiosk/edit', {
        headers: { cookie: 'sessionid=abc; csrftoken=xyz' },
      });
      const apiClient = createApiClient(fetch, 'http://127.0.0.1:8000', incoming);

      await apiClient.GET('/api/auth/me/');

      const request = fetch.mock.calls[0]?.[0] as Request;
      expect(request.headers.get('cookie')).toBe('sessionid=abc; csrftoken=xyz');
    });

    it('does not set a Cookie header when the incoming request has none', async () => {
      const fetch = vi.fn().mockResolvedValue(
        new Response(JSON.stringify({}), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
      const incoming = new Request('https://flipcommons.org/kiosk/edit');
      const apiClient = createApiClient(fetch, 'http://127.0.0.1:8000', incoming);

      await apiClient.GET('/api/auth/me/');

      const request = fetch.mock.calls[0]?.[0] as Request;
      expect(request.headers.get('cookie')).toBeNull();
    });
  });

  describe('public_id path-param slash preservation', () => {
    function makeClient() {
      const fetch = vi.fn().mockResolvedValue(
        new Response(JSON.stringify({}), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
      const apiClient = createApiClient(fetch, 'http://localhost:5173');
      return { fetch, apiClient };
    }

    it('preserves slashes in a multi-segment public_id', async () => {
      const { fetch, apiClient } = makeClient();
      await apiClient.GET('/api/corporate-entities/{public_id}/delete-preview/', {
        params: { path: { public_id: 'usa/il/chicago' } },
      });
      const url = new URL(fetch.mock.calls[0]?.[0].url);
      expect(url.pathname).toBe('/api/corporate-entities/usa/il/chicago/delete-preview/');
    });

    it('composes with CSRF: token attached and body preserved after URL rewrite', async () => {
      vi.stubGlobal('document', { cookie: 'csrftoken=abc123' });
      try {
        const { fetch, apiClient } = makeClient();
        await apiClient.POST('/api/corporate-entities/{public_id}/delete/', {
          params: { path: { public_id: 'usa/il/chicago' } },
          body: { note: 'hello', citations: [] },
        });
        const request = fetch.mock.calls[0]?.[0] as Request;
        expect(new URL(request.url).pathname).toBe(
          '/api/corporate-entities/usa/il/chicago/delete/',
        );
        expect(request.headers.get('X-CSRFToken')).toBe('abc123');
        expect(await request.text()).toBe(JSON.stringify({ note: 'hello', citations: [] }));
      } finally {
        vi.unstubAllGlobals();
      }
    });
  });

  describe('403-as-invalidation onResponse hook', () => {
    // Reset the module-level registration slot between tests so the
    // hook from one test doesn't leak into the next.
    beforeEach(() => {
      registerOnPolicyDenied(() => {});
    });
    afterEach(() => {
      // Drain by registering a no-op; there's no unregister API
      // (production has exactly one registrant: the auth store).
      registerOnPolicyDenied(() => {});
    });

    function makeFetch(status: number, body: unknown) {
      return vi.fn().mockResolvedValue(
        new Response(JSON.stringify(body), {
          status,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    }

    it('fires the registered callback on 403 with policy_denied body', async () => {
      const cb = vi.fn();
      registerOnPolicyDenied(cb);
      const fetch = makeFetch(403, {
        detail: {
          kind: 'policy_denied',
          message: 'Verify your email.',
          code: 'verification_required',
          context: {},
        },
      });
      const apiClient = createApiClient(fetch, 'http://localhost:5173');

      await apiClient.GET('/api/auth/me/');

      expect(cb).toHaveBeenCalledTimes(1);
    });

    it('does not fire on 403 without a policy_denied body', async () => {
      const cb = vi.fn();
      registerOnPolicyDenied(cb);
      const fetch = makeFetch(403, { detail: { kind: 'something_else' } });
      const apiClient = createApiClient(fetch, 'http://localhost:5173');

      await apiClient.GET('/api/auth/me/');

      expect(cb).not.toHaveBeenCalled();
    });

    it('does not fire on a non-403 response', async () => {
      const cb = vi.fn();
      registerOnPolicyDenied(cb);
      const fetch = makeFetch(200, { ok: true });
      const apiClient = createApiClient(fetch, 'http://localhost:5173');

      await apiClient.GET('/api/auth/me/');

      expect(cb).not.toHaveBeenCalled();
    });

    it('ignores responses whose body is not valid JSON', async () => {
      const cb = vi.fn();
      registerOnPolicyDenied(cb);
      const fetch = vi.fn().mockResolvedValue(
        new Response('<html>not json</html>', {
          status: 403,
          headers: { 'Content-Type': 'text/html' },
        }),
      );
      const apiClient = createApiClient(fetch, 'http://localhost:5173');

      await apiClient.GET('/api/auth/me/');

      expect(cb).not.toHaveBeenCalled();
    });
  });
});
