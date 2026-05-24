import { describe, expect, it, vi } from 'vitest';
import type { RequestEvent, ResolveOptions } from '@sveltejs/kit';
import type { RouteId } from '$app/types';

// Sentry mocks so importing hooks.server.ts doesn't drag in the real SDK.
vi.mock('@sentry/sveltekit', () => ({
  sentryHandle: vi.fn(() => vi.fn()),
  handleErrorWithSentry: vi.fn(() => vi.fn()),
}));
vi.mock('$lib/sentry/handle-error', () => ({ handleServerError: vi.fn() }));

// Spy on sequence() so we can pin membership of the exported `handle`
// without invoking SvelteKit's runtime request store (which sequence reads
// internally and which isn't set up in unit tests).
vi.mock('@sveltejs/kit/hooks', () => ({ sequence: vi.fn(() => vi.fn()) }));

const { sequence } = await import('@sveltejs/kit/hooks');
const { noindexHandle } = await import('./hooks.server');

function runHandle(
  routeId: RouteId | null,
  responseHtml = '<html><head></head><body></body></html>',
) {
  const resolve = vi.fn(async (_event: RequestEvent, opts?: ResolveOptions) => {
    let html = responseHtml;
    if (opts?.transformPageChunk) {
      const out = opts.transformPageChunk({ html, done: true });
      if (typeof out === 'string') html = out;
    }
    return new Response(html, { headers: { 'content-type': 'text/html' } });
  });
  const event = { route: { id: routeId } } as unknown as RequestEvent;
  return { resolve, promise: noindexHandle({ event, resolve }) };
}

describe('noindexHandle', () => {
  const CASES: ReadonlyArray<readonly [RouteId, boolean]> = [
    // Indexable.
    ['/', false],
    ['/about', false],
    ['/titles/[slug]', false],
    // Listed non-indexable.
    ['/login', true],
    ['/search', true],
    ['/users/[username]', true],
    // Auth-gated (via prefix scan).
    ['/admin/dashboard', true],
    ['/kiosk/edit', true],
    // Catalog non-indexable kinds.
    ['/titles', true],
    ['/titles/new', true],
    ['/titles/[slug]/edit', true],
    ['/titles/[slug]/delete', true],
  ];

  it.each(CASES)('classifies %s (noindex=%s)', async (routeId, expectedNoindex) => {
    const { resolve, promise } = runHandle(routeId);
    const response = await promise;

    if (expectedNoindex) {
      expect(response.headers.get('X-Robots-Tag')).toBe('noindex');
      expect(await response.text()).toContain('<meta name="robots" content="noindex"');
      expect(resolve).toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({ transformPageChunk: expect.any(Function) }),
      );
    } else {
      expect(response.headers.get('X-Robots-Tag')).toBeNull();
      expect(await response.text()).not.toContain('name="robots"');
      // No options passed at all on the indexable path.
      expect(resolve).toHaveBeenCalledWith(expect.anything());
    }
  });

  it('treats route.id === null (unmatched URLs / 404s) as noindex', async () => {
    const { promise } = runHandle(null);
    const response = await promise;

    expect(response.headers.get('X-Robots-Tag')).toBe('noindex');
    expect(await response.text()).toContain('<meta name="robots" content="noindex"');
  });

  it('treats unclassified routes (+server.ts endpoints like /__health) as noindex without throwing', async () => {
    // /__health has a +server.ts but no +page.svelte, so it's outside the
    // route-walking test's coverage and unclassified by isSearchEngineIndexable.
    // The hook must not crash on these — they hit the prod liveness probe.
    const { promise } = runHandle('/__health' as RouteId);
    const response = await promise;

    expect(response.headers.get('X-Robots-Tag')).toBe('noindex');
  });

  it('sets X-Robots-Tag on non-HTML responses without mangling the body', async () => {
    // The dual-signal rationale: the meta tag is impossible on non-HTML
    // responses, so the header is the only signal that can land. Stub a JSON
    // response (no </head>) and assert the body is byte-identical — the
    // html.replace no-ops correctly when there's nothing to replace, and the
    // header still fires.
    const jsonBody = '{"status":"ok"}';
    const resolve = vi.fn(async (_event: RequestEvent, opts?: ResolveOptions) => {
      let body = jsonBody;
      if (opts?.transformPageChunk) {
        const out = opts.transformPageChunk({ html: body, done: true });
        if (typeof out === 'string') body = out;
      }
      return new Response(body, { headers: { 'content-type': 'application/json' } });
    });
    const event = { route: { id: '/__health' as RouteId } } as unknown as RequestEvent;

    const response = await noindexHandle({ event, resolve });

    expect(response.headers.get('X-Robots-Tag')).toBe('noindex');
    expect(await response.text()).toBe(jsonBody);
  });
});

describe('exported handle sequence', () => {
  // The bare `noindexHandle` tests above all import the handle directly.
  // They'd keep passing if a future edit dropped noindexHandle from
  // `sequence(...)` — the hook would silently never fire in prod. Pin the
  // structural claim that noindexHandle is in the sequence.
  it('passes noindexHandle to sequence()', () => {
    // Position-agnostic so a future hook added to the sequence (e.g. the
    // canonical-URL hook from CanonicalUrl.md) doesn't break this assertion.
    const [args] = vi.mocked(sequence).mock.calls;
    expect(args).toContain(noindexHandle);
  });
});
