import { describe, expect, it, vi } from 'vitest';
import { loadEditHistory, loadSources } from './provenance-loaders';

const MOCK_CHANGESETS = [
  {
    id: 1,
    created_at: '2025-01-01T00:00:00Z',
    user: { id: 1, username: 'admin' },
    changes: [],
  },
];

const MOCK_SOURCES_PAYLOAD = {
  sources: [{ id: 1, name: 'IPDB', priority: 10 }],
};

function makeEvent(fetch: typeof globalThis.fetch, path: string) {
  const url = new URL(`http://localhost:5173${path}`);
  return {
    fetch,
    url,
    request: new Request(url),
  };
}

describe('loadEditHistory', () => {
  it('calls the edit-history page API for the given entity type and public_id', async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(MOCK_CHANGESETS), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const result = await loadEditHistory(
      makeEvent(fetch, '/models/medieval-madness/edit-history'),
      'model',
      'medieval-madness',
    );

    expect(result).toEqual({ changesets: MOCK_CHANGESETS });
    const request = fetch.mock.calls[0]?.[0] as Request;
    expect(request).toBeInstanceOf(Request);
    expect(request.url).toBe(
      'http://localhost:5173/api/pages/edit-history/model/medieval-madness/',
    );
  });

  it('throws with the upstream status on backend failure', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('Server error', { status: 500 }));

    await expect(
      loadEditHistory(
        makeEvent(fetch, '/models/medieval-madness/edit-history'),
        'model',
        'medieval-madness',
      ),
    ).rejects.toMatchObject({ status: 500 });
  });
});

describe('loadSources', () => {
  it('calls the sources page API and returns the claim list', async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(MOCK_SOURCES_PAYLOAD), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const result = await loadSources(
      makeEvent(fetch, '/models/medieval-madness/sources'),
      'model',
      'medieval-madness',
    );

    expect(result).toEqual(MOCK_SOURCES_PAYLOAD);
    const request = fetch.mock.calls[0]?.[0] as Request;
    expect(request).toBeInstanceOf(Request);
    expect(request.url).toBe('http://localhost:5173/api/pages/sources/model/medieval-madness/');
  });

  it('throws with the upstream status on backend failure', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('Server error', { status: 500 }));

    await expect(
      loadSources(
        makeEvent(fetch, '/models/medieval-madness/sources'),
        'model',
        'medieval-madness',
      ),
    ).rejects.toMatchObject({ status: 500 });
  });
});
