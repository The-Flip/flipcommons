import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { BlockingReferrer } from './delete-flow';

const POST = vi.fn();

vi.mock('$lib/api/client', () => ({
  default: { POST },
}));

vi.mock('$lib/edit-citation', () => ({
  buildEditCitationsRequest: () => [],
}));

// Import after mocks so the module closes over the mocked client.
const { createDeleteSubmitter, referrerHref } = await import('./delete-flow');

function makeResponse(
  body: BodyInit | null,
  status: number,
  headers: Record<string, string> = {},
): Response {
  return new Response(body, { status, headers });
}

beforeEach(() => {
  POST.mockReset();
});

describe('createDeleteSubmitter', () => {
  const submit = createDeleteSubmitter('themes');

  it('passes the public_id through to the configured endpoint', async () => {
    POST.mockResolvedValue({
      data: { changeset_id: 1 },
      error: undefined,
      response: makeResponse(null, 200),
    });
    await submit('abc');
    expect(POST).toHaveBeenCalledWith('/api/themes/{public_id}/delete/', expect.anything());
    const callBody = POST.mock.calls[0][1];
    expect(callBody.params.path.public_id).toBe('abc');
  });

  it('returns ok with the typed response on 200', async () => {
    POST.mockResolvedValue({
      data: { changeset_id: 42 },
      error: undefined,
      response: makeResponse(null, 200),
    });
    const out = await submit('abc');
    expect(out.kind).toBe('ok');
    if (out.kind === 'ok') expect(out.data.changeset_id).toBe(42);
  });

  it('classifies 429 as rate_limited and formats Retry-After as hours', async () => {
    POST.mockResolvedValue({
      data: undefined,
      error: undefined,
      response: makeResponse(null, 429, { 'Retry-After': '86400' }),
    });
    const out = await submit('abc');
    expect(out.kind).toBe('rate_limited');
    if (out.kind === 'rate_limited') {
      expect(out.retryAfterSeconds).toBe(86400);
      expect(out.message).toMatch(/\d+ hour/);
    }
  });

  it('defaults Retry-After to one day when the header is missing', async () => {
    POST.mockResolvedValue({
      data: undefined,
      error: undefined,
      response: makeResponse(null, 429),
    });
    const out = await submit('abc');
    if (out.kind === 'rate_limited') expect(out.retryAfterSeconds).toBe(86400);
  });

  it('classifies 422 with blocked_by as a blocked outcome', async () => {
    const body = {
      detail: 'Cannot delete: active references.',
      blocked_by: [
        {
          entity_type: 'model',
          public_id: 'other',
          name: 'Other',
          relation: 'variant_of',
          blocked_target_type: 'model',
          blocked_target_public_id: 'target',
        },
      ],
    };
    POST.mockResolvedValue({
      data: undefined,
      error: body,
      response: makeResponse(JSON.stringify(body), 422, { 'content-type': 'application/json' }),
    });
    const out = await submit('target');
    expect(out.kind).toBe('blocked');
    if (out.kind === 'blocked') {
      expect(out.blockedBy).toHaveLength(1);
      expect(out.blockedBy[0].public_id).toBe('other');
      expect(out.message).toContain('active references');
    }
  });

  it('exposes entity-specific 422 fields on the blocked outcome.extra', async () => {
    const body = {
      detail: 'Cannot delete: credited on 3 active machines. Remove credits first.',
      blocked_by: [],
      active_credit_count: 3,
    };
    POST.mockResolvedValue({
      data: undefined,
      error: body,
      response: makeResponse(JSON.stringify(body), 422, { 'content-type': 'application/json' }),
    });
    const out = await submit('keith-johnson');
    expect(out.kind).toBe('blocked');
    if (out.kind === 'blocked') {
      expect(out.blockedBy).toEqual([]);
      expect(out.extra.active_credit_count).toBe(3);
      expect(out.message).toContain('3 active machines');
    }
  });

  it('falls back to form_error for unexpected failures', async () => {
    POST.mockResolvedValue({
      data: undefined,
      error: { detail: 'server blew up' },
      response: makeResponse(null, 500),
    });
    const out = await submit('abc');
    expect(out.kind).toBe('form_error');
    if (out.kind === 'form_error') expect(out.message).toContain('server blew up');
  });

  it('falls back to form_error when a 422 body has no blocked_by', async () => {
    // 422s from the generic validation path look like this.
    const body = { detail: 'something invalid' };
    POST.mockResolvedValue({
      data: undefined,
      error: body,
      response: makeResponse(JSON.stringify(body), 422, { 'content-type': 'application/json' }),
    });
    const out = await submit('abc');
    expect(out.kind).toBe('form_error');
  });
});

describe('referrerHref', () => {
  function referrer(overrides: Partial<BlockingReferrer> = {}): BlockingReferrer {
    return {
      entity_type: 'model',
      public_id: 'medieval-madness-le',
      name: 'Medieval Madness LE',
      relation: 'title',
      blocked_target_type: 'title',
      blocked_target_public_id: 'medieval-madness',
      ...overrides,
    };
  }

  it('builds the href from the entity registry rather than the referrer type', () => {
    expect(referrerHref(referrer())).toBe('/models/medieval-madness-le');
    expect(
      referrerHref(referrer({ entity_type: 'corporate-entity', public_id: 'gottlieb-co' })),
    ).toBe('/corporate-entities/gottlieb-co');
  });

  it('addresses an entity by its public_id even when that is not a bare slug', () => {
    expect(referrerHref(referrer({ entity_type: 'location', public_id: 'usa/tx/paris' }))).toBe(
      '/locations/usa/tx/paris',
    );
  });

  it('returns null for an entity_type outside the catalog vocabulary', () => {
    expect(referrerHref(referrer({ entity_type: 'sandwich' }))).toBeNull();
  });
});
