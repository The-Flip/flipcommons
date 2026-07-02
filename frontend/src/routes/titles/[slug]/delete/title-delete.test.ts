import { beforeEach, describe, expect, it, vi } from 'vitest';

const POST = vi.fn();

vi.mock('$lib/api/client', () => ({
  default: { POST },
}));

vi.mock('$lib/edit-citation', () => ({
  buildEditCitationsRequest: () => [],
}));

// Import after mocks so the module closes over the mocked client.
const { submitDelete } = await import('./title-delete');

beforeEach(() => {
  POST.mockReset();
});

describe('title submitDelete', () => {
  // The classification logic is covered by lib/delete-flow.test.ts; this
  // smoke test only verifies that title-delete.ts points the factory at
  // the right endpoint.
  it('posts to /api/titles/{public_id}/delete/', async () => {
    POST.mockResolvedValue({
      data: { changeset_id: 42, affected_titles: ['g'], affected_models: [] },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    const out = await submitDelete('g');
    expect(POST).toHaveBeenCalledWith('/api/titles/{public_id}/delete/', expect.anything());
    expect(POST.mock.calls[0][1].params.path.public_id).toBe('g');
    expect(out.kind).toBe('ok');
  });
});
