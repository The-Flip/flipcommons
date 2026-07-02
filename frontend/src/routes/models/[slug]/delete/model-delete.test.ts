import { beforeEach, describe, expect, it, vi } from 'vitest';

const POST = vi.fn();

vi.mock('$lib/api/client', () => ({
  default: { POST },
}));

vi.mock('$lib/edit-citation', () => ({
  buildEditCitationsRequest: () => [],
}));

// Import after mocks so the module closes over the mocked client.
const { submitDelete } = await import('./model-delete');

beforeEach(() => {
  POST.mockReset();
});

describe('model submitDelete', () => {
  // The classification logic is covered by lib/delete-flow.test.ts; this
  // smoke test only verifies that model-delete.ts points the factory at
  // the right endpoint.
  it('posts to /api/models/{public_id}/delete/', async () => {
    POST.mockResolvedValue({
      data: { changeset_id: 42, affected_slugs: ['mm-pro'] },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    const out = await submitDelete('mm-pro');
    expect(POST).toHaveBeenCalledWith('/api/models/{public_id}/delete/', expect.anything());
    expect(POST.mock.calls[0][1].params.path.public_id).toBe('mm-pro');
    expect(out.kind).toBe('ok');
  });
});
