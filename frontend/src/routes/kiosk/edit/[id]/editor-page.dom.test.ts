import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { goto, resolve, GET, PATCH, DELETE, POST } = vi.hoisted(() => ({
  goto: vi.fn(),
  resolve: vi.fn((url: string) => url),
  GET: vi.fn(),
  PATCH: vi.fn(),
  DELETE: vi.fn(),
  POST: vi.fn(),
}));

vi.mock('$app/navigation', () => ({ goto }));
vi.mock('$app/paths', () => ({ resolve }));
vi.mock('$lib/api/client', () => ({ default: { GET, PATCH, DELETE, POST } }));

import Page from './+page.svelte';
import { clearKioskCookies, setKioskCookies } from '$lib/kiosk/config';
import { toast } from '$lib/toast/toast.svelte';

function makeData(
  overrides: Partial<{ id: number; page_heading: string; idle_seconds: number }> = {},
  activeId: number | null = null,
) {
  return {
    config: {
      id: 7,
      page_heading: '',
      idle_seconds: 60,
      items: [],
      ...overrides,
    },
    activeId,
  };
}

describe('/kiosk/edit/[id] editor — delete handler', () => {
  beforeEach(() => {
    goto.mockReset().mockResolvedValue(undefined);
    GET.mockReset().mockResolvedValue({ data: [] });
    PATCH.mockReset();
    DELETE.mockReset();
    clearKioskCookies();
    toast._resetForTest();
  });

  afterEach(() => {
    toast._resetForTest();
  });

  it('cancelled confirm: no DELETE, no goto, cookies untouched', async () => {
    const user = userEvent.setup();
    setKioskCookies(7, 60);
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);

    render(Page, { data: makeData() });
    await user.click(screen.getAllByRole('button', { name: 'Delete Kiosk' })[0]);

    expect(confirmSpy).toHaveBeenCalled();
    expect(DELETE).not.toHaveBeenCalled();
    expect(goto).not.toHaveBeenCalled();
    expect(document.cookie).toContain('mode=kiosk');
    expect(document.cookie).toContain('kioskConfigId=7');
    confirmSpy.mockRestore();
  });

  it('confirmed, non-active config: DELETE called, goto fires, cookies untouched', async () => {
    const user = userEvent.setup();
    setKioskCookies(99, 60); // active is a DIFFERENT kiosk
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    DELETE.mockResolvedValue({ response: { status: 204 }, error: undefined });

    render(Page, { data: makeData() });
    await user.click(screen.getAllByRole('button', { name: 'Delete Kiosk' })[0]);

    await waitFor(() => expect(DELETE).toHaveBeenCalledTimes(1));
    expect(DELETE).toHaveBeenCalledWith('/api/kiosk/configs/{config_id}/', {
      params: { path: { config_id: 7 } },
    });
    expect(goto).toHaveBeenCalledWith('/kiosk/edit');
    // Other-kiosk cookie left intact.
    expect(document.cookie).toContain('kioskConfigId=99');
    confirmSpy.mockRestore();
  });

  it('confirmed, active config: cookies cleared BEFORE DELETE call', async () => {
    const user = userEvent.setup();
    setKioskCookies(7, 60); // active matches
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    let cookieAtDeleteTime: string | null = null;
    DELETE.mockImplementation(async () => {
      cookieAtDeleteTime = document.cookie;
      return { response: { status: 204 }, error: undefined };
    });

    render(Page, { data: makeData() });
    await user.click(screen.getAllByRole('button', { name: 'Delete Kiosk' })[0]);

    await waitFor(() => expect(DELETE).toHaveBeenCalled());
    expect(cookieAtDeleteTime).not.toContain('kioskConfigId=7');
    expect(cookieAtDeleteTime).not.toContain('mode=kiosk');
    expect(goto).toHaveBeenCalledWith('/kiosk/edit');
    confirmSpy.mockRestore();
  });

  it('DELETE failure: no goto, error message rendered', async () => {
    const user = userEvent.setup();
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    DELETE.mockResolvedValue({ response: { status: 500 }, error: { detail: 'boom' } });

    render(Page, { data: makeData() });
    await user.click(screen.getAllByRole('button', { name: 'Delete Kiosk' })[0]);

    await waitFor(() => expect(DELETE).toHaveBeenCalled());
    expect(goto).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    confirmSpy.mockRestore();
  });
});

describe('/kiosk/edit/[id] editor — autosave on blur', () => {
  beforeEach(() => {
    goto.mockReset().mockResolvedValue(undefined);
    GET.mockReset().mockResolvedValue({ data: [] });
    PATCH.mockReset();
    clearKioskCookies();
    toast._resetForTest();
  });

  it('blurring page-heading PATCHes the current state', async () => {
    const user = userEvent.setup();
    PATCH.mockResolvedValue({
      data: { id: 7, page_heading: 'Welcome', idle_seconds: 60, items: [] },
      error: undefined,
    });

    render(Page, { data: makeData() });
    const headingInput = screen.getByLabelText(/Front door heading/i);
    await user.clear(headingInput);
    await user.type(headingInput, 'Welcome');
    await user.tab(); // blur

    await waitFor(() => expect(PATCH).toHaveBeenCalled());
    expect(PATCH).toHaveBeenCalledWith(
      '/api/kiosk/configs/{config_id}/',
      expect.objectContaining({
        body: expect.objectContaining({ page_heading: 'Welcome' }),
      }),
    );
  });

  it('coalesces overlapping saves: a blur during an in-flight save fires exactly one trailing PATCH', async () => {
    const user = userEvent.setup();
    // Hold the first PATCH until we explicitly resolve it so the second
    // blur lands while the first is still in flight.
    let resolveFirst!: (v: unknown) => void;
    const firstPromise = new Promise((r) => {
      resolveFirst = r;
    });
    PATCH.mockImplementationOnce(() => firstPromise).mockResolvedValue({
      data: { id: 7, page_heading: 'H', idle_seconds: 90, items: [] },
      error: undefined,
    });

    render(Page, { data: makeData() });
    const headingInput = screen.getByLabelText(/Front door heading/i);
    const idleInput = screen.getByLabelText(/Idle timeout/i);

    await user.clear(headingInput);
    await user.type(headingInput, 'H');
    await user.tab(); // blur heading → first save starts and hangs
    await waitFor(() => expect(PATCH).toHaveBeenCalledTimes(1));

    // While the first is still pending, edit + blur a second field.
    await user.clear(idleInput);
    await user.type(idleInput, '90');
    await user.tab();
    // No second PATCH yet — coalescer should be holding it.
    expect(PATCH).toHaveBeenCalledTimes(1);

    // Resolve the first save. The trailing save should fire with the
    // current state (both fields).
    resolveFirst({
      data: { id: 7, page_heading: 'H', idle_seconds: 60, items: [] },
      error: undefined,
    });
    await waitFor(() => expect(PATCH).toHaveBeenCalledTimes(2));
    expect(PATCH).toHaveBeenLastCalledWith(
      '/api/kiosk/configs/{config_id}/',
      expect.objectContaining({
        body: expect.objectContaining({ page_heading: 'H', idle_seconds: 90 }),
      }),
    );
  });

  it('blurring idle-seconds refreshes the kioskIdleSeconds cookie when this device is active', async () => {
    const user = userEvent.setup();
    setKioskCookies(7, 60);
    PATCH.mockResolvedValue({
      data: { id: 7, page_heading: '', idle_seconds: 120, items: [] },
      error: undefined,
    });

    render(Page, { data: makeData() });
    const idleInput = screen.getByLabelText(/Idle timeout/i);
    await user.clear(idleInput);
    await user.type(idleInput, '120');
    await user.tab(); // blur

    await waitFor(() => expect(PATCH).toHaveBeenCalled());
    await waitFor(() => expect(document.cookie).toContain('kioskIdleSeconds=120'));
  });
});

describe('/kiosk/edit/[id] editor — Enter/Exit Kiosk Mode button', () => {
  beforeEach(() => {
    goto.mockReset().mockResolvedValue(undefined);
    GET.mockReset().mockResolvedValue({ data: [] });
    clearKioskCookies();
  });

  it('shows "Enter Kiosk Mode" when this device is not the active kiosk', () => {
    render(Page, { data: makeData({}, null) });
    expect(screen.getAllByRole('button', { name: 'Enter Kiosk Mode' }).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: 'Exit Kiosk Mode' })).toBeNull();
  });

  it('shows "Enter Kiosk Mode" when active kiosk is a different config', () => {
    render(Page, { data: makeData({}, 99) });
    expect(screen.getAllByRole('button', { name: 'Enter Kiosk Mode' }).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: 'Exit Kiosk Mode' })).toBeNull();
  });

  it('shows "Exit Kiosk Mode" when this config is active on this device', () => {
    render(Page, { data: makeData({}, 7) });
    expect(screen.getAllByRole('button', { name: 'Exit Kiosk Mode' }).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: 'Enter Kiosk Mode' })).toBeNull();
  });

  it('clicking "Exit Kiosk Mode" clears cookies and swaps the button to "Enter Kiosk Mode"', async () => {
    const user = userEvent.setup();
    setKioskCookies(7, 60);

    render(Page, { data: makeData({}, 7) });
    await user.click(screen.getAllByRole('button', { name: 'Exit Kiosk Mode' })[0]);

    expect(document.cookie).not.toContain('kioskConfigId=7');
    expect(document.cookie).not.toContain('mode=kiosk');
    expect(screen.queryByRole('button', { name: 'Exit Kiosk Mode' })).toBeNull();
    expect(screen.getAllByRole('button', { name: 'Enter Kiosk Mode' }).length).toBeGreaterThan(0);
  });
});

describe('/kiosk/edit/[id] editor — "Add a machine" typeahead', () => {
  // Rows the entity-autocomplete endpoint returns, filtered by the typed query.
  const AUTOCOMPLETE_ROWS = [
    { value: 'medieval-madness-title', label: 'Medieval Madness', sublabel: 'Williams · 1997' },
    { value: 'attack-from-mars-title', label: 'Attack from Mars', sublabel: 'Bally · 1995' },
  ];

  function dataWithItem() {
    return {
      config: {
        id: 7,
        page_heading: '',
        idle_seconds: 60,
        items: [
          {
            id: 1,
            position: 1,
            hook: '',
            title: {
              public_id: 'attack-from-mars-title',
              name: 'Attack from Mars',
              manufacturer: { name: 'Bally', public_id: 'bally' },
              year: 1995,
            },
          },
        ],
      },
      activeId: null,
    };
  }

  beforeEach(() => {
    goto.mockReset().mockResolvedValue(undefined);
    PATCH.mockReset().mockResolvedValue({
      data: { id: 7, page_heading: '', idle_seconds: 60, items: [] },
      error: undefined,
    });
    GET.mockReset().mockImplementation(
      async (path: string, opts?: { params?: { query?: { type?: string; q?: string } } }) => {
        if (path === '/api/entity-autocomplete/') {
          const q = (opts?.params?.query?.q ?? '').toLowerCase();
          const results = AUTOCOMPLETE_ROWS.filter((r) => r.label.toLowerCase().includes(q));
          return { data: { results }, error: undefined, response: { status: 200 } };
        }
        // The retired /api/titles/all/ blob must never be fetched.
        throw new Error(`Unexpected GET ${path}`);
      },
    );
    clearKioskCookies();
    toast._resetForTest();
  });

  afterEach(() => {
    toast._resetForTest();
  });

  it('renders an already-configured row with its manufacturer · year sublabel and no network', () => {
    render(Page, { data: dataWithItem() });

    expect(screen.getByText(/Attack from Mars/)).toBeInTheDocument();
    expect(screen.getByText(/Bally · 1995/)).toBeInTheDocument();
    // Initial render is network-free — no titles/all, no autocomplete.
    expect(GET).not.toHaveBeenCalled();
  });

  it('queries entity-autocomplete by title, excludes configured rows, and adds + saves a pick', async () => {
    const user = userEvent.setup();
    render(Page, { data: dataWithItem() });

    await user.type(screen.getByLabelText('Add a machine'), 'm');
    await waitFor(() =>
      expect(GET).toHaveBeenLastCalledWith('/api/entity-autocomplete/', {
        params: { query: { type: 'title', q: 'm' } },
      }),
    );

    // The already-configured "Attack from Mars" is filtered out of results.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Medieval Madness/ })).toBeInTheDocument(),
    );
    expect(
      screen.queryByRole('button', { name: /Attack from Mars · Bally/ }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Medieval Madness/ }));

    // Selecting a row appends it and auto-saves with both title slugs.
    await waitFor(() => expect(PATCH).toHaveBeenCalledTimes(1));
    expect(PATCH).toHaveBeenCalledWith(
      '/api/kiosk/configs/{config_id}/',
      expect.objectContaining({
        body: expect.objectContaining({
          items: [
            expect.objectContaining({ title_slug: 'attack-from-mars-title' }),
            expect.objectContaining({ title_slug: 'medieval-madness-title' }),
          ],
        }),
      }),
    );

    // The freshly-added row shows its sublabel from the autocomplete result.
    expect(screen.getByText(/Williams · 1997/)).toBeInTheDocument();

    // The retired load-all feeder is never touched.
    expect(GET.mock.calls.map((c) => c[0])).not.toContain('/api/titles/all/');
  });
});
