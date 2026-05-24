import { beforeEach, describe, expect, it, vi } from 'vitest';

const requireCapability = vi.fn();

vi.mock('$lib/require-capability.server', () => ({
  requireCapability: (...args: unknown[]) => requireCapability(...args),
}));

const { load } = await import('./+layout.server');

function makeEvent(url: URL) {
  const fetchStub = (() => undefined) as unknown as typeof globalThis.fetch;
  const request = new Request(url);
  return { fetch: fetchStub, url, request };
}

describe('/admin +layout.server.ts load', () => {
  beforeEach(() => {
    requireCapability.mockReset();
  });

  it('gates the admin area through requireCapability with admin_area.view', async () => {
    requireCapability.mockResolvedValueOnce(undefined);
    const event = makeEvent(new URL('http://localhost/admin/dashboard'));

    await load(event as unknown as Parameters<typeof load>[0]);

    expect(requireCapability).toHaveBeenCalledWith({
      fetch: event.fetch,
      url: event.url,
      request: event.request,
      activity: 'admin_area.view',
    });
  });

  it('propagates the redirect/error thrown by requireCapability', async () => {
    const denied = Object.assign(new Error('redirect'), { status: 302, location: '/login' });
    requireCapability.mockRejectedValueOnce(denied);
    const event = makeEvent(new URL('http://localhost/admin/dashboard'));

    await expect(load(event as unknown as Parameters<typeof load>[0])).rejects.toBe(denied);
  });
});
