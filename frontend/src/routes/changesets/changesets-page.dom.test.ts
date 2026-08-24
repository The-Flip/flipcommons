import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SvelteURL } from 'svelte/reactivity';

const { goto, pageState } = vi.hoisted(() => ({
  // Resolves only when a test lets it: an unsettled `goto` stands in for a
  // navigation still in flight, which is when filter intents can race.
  goto: vi.fn(() => new Promise<void>(() => {})),
  // The component derives its filters from `page.url`, so the mock URL has to
  // be reactive: a test mutates it to stand in for a landing/back-navigation.
  pageState: {} as { url: URL },
}));
vi.mock('$app/navigation', () => ({ goto }));
vi.mock('$app/state', () => ({ page: pageState }));

const { mockGET } = vi.hoisted(() => ({ mockGET: vi.fn() }));
vi.mock('$lib/api/client', () => ({ default: { GET: mockGET } }));

import Page from './+page.svelte';

/** Point the mocked `page.url` at a fresh reactive URL with `search`. */
function atUrl(search: string) {
  pageState.url = new SvelteURL(`http://localhost/changesets${search}`);
  return pageState.url;
}

/** The query object of the nth list request the component issued. */
function listQuery(nth = 0) {
  const calls = mockGET.mock.calls.filter(([path]) => path === '/api/pages/changesets/');
  return calls[nth]?.[1].params.query;
}

function listCallCount() {
  return mockGET.mock.calls.filter(([path]) => path === '/api/pages/changesets/').length;
}

beforeEach(() => {
  goto.mockReset();
  goto.mockImplementation(() => new Promise<void>(() => {}));
  mockGET.mockReset();
  mockGET.mockResolvedValue({ data: { items: [], next_cursor: null } });
  atUrl('');
});

describe('/changesets filters ⇄ query string', () => {
  it('seeds both dropdowns from the query string', async () => {
    atUrl('?entity_type=model&range=7d');
    render(Page);

    expect(await screen.findByLabelText('Entry type')).toHaveValue('model');
    expect(screen.getByLabelText('Time range')).toHaveValue('7d');
  });

  it('sends the query string filters to the API on first load', async () => {
    atUrl('?entity_type=manufacturer&range=24h');
    render(Page);

    await waitFor(() => expect(listCallCount()).toBe(1));
    expect(listQuery()).toMatchObject({ entity_type: 'manufacturer' });
    // `range` is a UI window; the API sees the resolved lower bound.
    expect(listQuery().after).toEqual(expect.any(String));
  });

  it('puts a chosen entity type into the query string', async () => {
    render(Page);
    await screen.findByLabelText('Entry type');

    await userEvent.selectOptions(screen.getByLabelText('Entry type'), 'model');

    expect(goto).toHaveBeenCalledWith('/changesets?entity_type=model', expect.anything());
  });

  it('puts a chosen time range into the query string, keeping the entity type', async () => {
    atUrl('?entity_type=model');
    render(Page);
    await screen.findByLabelText('Time range');

    await userEvent.selectOptions(screen.getByLabelText('Time range'), '30d');

    expect(goto).toHaveBeenCalledWith('/changesets?entity_type=model&range=30d', expect.anything());
  });

  it('drops the param again when a filter is cleared', async () => {
    atUrl('?entity_type=model&range=30d');
    render(Page);
    await screen.findByLabelText('Entry type');

    await userEvent.selectOptions(screen.getByLabelText('Entry type'), '');

    expect(goto).toHaveBeenCalledWith('/changesets?range=30d', expect.anything());
  });

  it('ignores an unknown filter value in the query string', async () => {
    atUrl('?entity_type=widget&range=1y');
    render(Page);

    await waitFor(() => expect(listCallCount()).toBe(1));
    expect(await screen.findByLabelText('Entry type')).toHaveValue('');
    expect(listQuery()).toMatchObject({ entity_type: undefined, after: undefined });
  });

  it('composes a second filter change on the first while its navigation is in flight', async () => {
    render(Page);
    await screen.findByLabelText('Entry type');

    // Neither `goto` settles, so `page.url` never advances — the window in
    // which a second intent would otherwise build on pre-navigation state.
    await userEvent.selectOptions(screen.getByLabelText('Entry type'), 'model');
    await userEvent.selectOptions(screen.getByLabelText('Time range'), '30d');

    expect(goto).toHaveBeenLastCalledWith(
      '/changesets?entity_type=model&range=30d',
      expect.anything(),
    );
  });

  it('reloads the feed when a filter actually changes', async () => {
    const url = atUrl('?entity_type=model');
    render(Page);
    await waitFor(() => expect(listCallCount()).toBe(1));

    url.search = '?entity_type=person';

    await waitFor(() => expect(listCallCount()).toBe(2));
    expect(listQuery(1)).toMatchObject({ entity_type: 'person' });
  });

  it('does not reload the feed for a URL change that leaves the filters alone', async () => {
    const url = atUrl('?entity_type=model');
    render(Page);
    await waitFor(() => expect(listCallCount()).toBe(1));

    url.search = '?entity_type=model&utm_source=newsletter';

    // Give the effect the chance to fire that the previous assertion proves it takes.
    await new Promise((r) => setTimeout(r, 0));
    expect(listCallCount()).toBe(1);
  });
});
