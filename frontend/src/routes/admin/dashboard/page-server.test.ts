import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiGet = vi.fn();

vi.mock('$lib/api/server', () => ({
  createServerClient: () => ({ GET: apiGet }),
}));

const { load } = await import('./+page.server');

type LoadEvent = Parameters<typeof load>[0];

function makeEvent(): LoadEvent {
  const fetchStub = (() => undefined) as unknown as typeof globalThis.fetch;
  return {
    fetch: fetchStub,
    url: new URL('http://localhost/admin/dashboard'),
    request: new Request('http://localhost/admin/dashboard'),
    depends: vi.fn(),
  } as unknown as LoadEvent;
}

const samplePayload = {
  signups: { last_24h: 1, last_7d: 2, total: 3, last_at: '2026-05-18T18:00:00Z' },
  edits: { last_24h: 0, last_7d: 0, total: 0, last_at: null },
  uploads: { last_24h: 1, last_7d: 1, total: 1, last_at: '2026-05-18T18:00:00Z' },
  generated_at: '2026-05-18T18:00:00Z',
};

describe('/admin/dashboard +page.server.ts load', () => {
  beforeEach(() => {
    apiGet.mockReset();
  });

  it('registers the invalidation dependency key', async () => {
    const { ADMIN_DASHBOARD_DEPEND_KEY } = await import('./_dependencies');
    apiGet.mockResolvedValueOnce({ data: samplePayload, response: { status: 200 } });
    const event = makeEvent();
    await load(event);
    expect(event.depends).toHaveBeenCalledWith(ADMIN_DASHBOARD_DEPEND_KEY);
  });

  it('returns the typed stats payload on success', async () => {
    apiGet.mockResolvedValueOnce({ data: samplePayload, response: { status: 200 } });
    const result = await load(makeEvent());
    expect(result).toEqual({ stats: samplePayload });
  });

  it('throws an error with the upstream status when the page-API fails', async () => {
    apiGet.mockResolvedValueOnce({ data: undefined, response: { status: 503 } });
    await expect(load(makeEvent())).rejects.toMatchObject({ status: 503 });
  });
});
