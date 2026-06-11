import { describe, expect, it, vi } from 'vitest';
import { render } from 'svelte/server';
import Page from './+page.svelte';
import { load } from './+layout.server';
import { MOCK_CORPORATE_ENTITY as MOCK_DATA } from './corporate-entity.fixtures';

describe('corporate-entities detail SSR route', () => {
  it('loads from the page endpoint', async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(MOCK_DATA), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const result = await load({
      fetch,
      url: new URL('http://localhost:5173/corporate-entities/williams-electronics'),
      params: { slug: 'williams-electronics' },
    } as unknown as Parameters<typeof load>[0]);

    expect(result).toEqual(expect.objectContaining({ profile: MOCK_DATA }));
    const request = fetch.mock.calls[0]?.[0];
    expect(request).toBeInstanceOf(Request);
    expect(request.url).toBe(
      'http://localhost:5173/api/pages/corporate-entity/williams-electronics',
    );
  });

  it('throws 404 when not found', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('Not found', { status: 404 }));

    await expect(
      load({
        fetch,
        url: new URL('http://localhost:5173/corporate-entities/nonexistent'),
        params: { slug: 'nonexistent' },
      } as unknown as Parameters<typeof load>[0]),
    ).rejects.toMatchObject({ status: 404 });
  });

  it('renders meaningful content into initial HTML', () => {
    const { body } = render(Page, {
      props: {
        data: { profile: MOCK_DATA, jsonLd: {} },
      },
    });

    expect(body).toContain('Medieval Madness');
  });

  it('renders the empty-state message when there are no titles', () => {
    const { body } = render(Page, {
      props: {
        data: { profile: { ...MOCK_DATA, titles: [] }, jsonLd: {} },
      },
    });

    expect(body).toContain('No titles listed for this corporate entity.');
  });
});
