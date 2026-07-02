import { beforeEach, describe, expect, it, vi } from 'vitest';

const POST = vi.fn();

vi.mock('$lib/api/client', () => ({
  default: { POST },
}));

vi.mock('$lib/edit-citation', () => ({
  buildEditCitationsRequest: () => [],
}));

// Import after mocks so the module closes over the mocked client.
const { submitDelete } = await import('./person-delete');

beforeEach(() => {
  POST.mockReset();
});

describe('person submitDelete', () => {
  // The classification logic is covered by lib/delete-flow.test.ts; this
  // smoke test only verifies that person-delete.ts points the factory at
  // the right endpoint and that the person-specific 422 extras surface on
  // ``outcome.extra``.
  it('posts to /api/people/{public_id}/delete/', async () => {
    POST.mockResolvedValue({
      data: { changeset_id: 42, affected_slugs: ['pat-lawlor'] },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    const out = await submitDelete('pat-lawlor');
    expect(POST).toHaveBeenCalledWith('/api/people/{public_id}/delete/', expect.anything());
    expect(POST.mock.calls[0][1].params.path.public_id).toBe('pat-lawlor');
    expect(out.kind).toBe('ok');
  });

  it('exposes active_credit_count on the blocked outcome', async () => {
    const body = {
      detail:
        'Cannot delete: Pat Lawlor is credited on 5 active machines. Remove the credits first.',
      blocked_by: [],
      active_credit_count: 5,
    };
    POST.mockResolvedValue({
      data: undefined,
      error: body,
      response: new Response(JSON.stringify(body), {
        status: 422,
        headers: { 'content-type': 'application/json' },
      }),
    });
    const out = await submitDelete('pat-lawlor');
    expect(out.kind).toBe('blocked');
    if (out.kind === 'blocked') {
      expect(out.extra.active_credit_count).toBe(5);
      expect(out.message).toContain('5 active machines');
    }
  });
});
