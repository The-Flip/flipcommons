import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { flushSync } from 'svelte';
import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import WikilinkAutocomplete from './WikilinkAutocomplete.svelte';
import { searchLinkTargets } from '$lib/api/link-types';
import { SEARCH_RESULTS } from './link-types-fixtures';

vi.mock('$lib/api/link-types', async () => {
  const f = await import('./link-types-fixtures');
  return {
    fetchLinkTypes: vi.fn().mockResolvedValue(f.LINK_TYPES),
    searchLinkTargets: vi.fn().mockResolvedValue({ results: f.SEARCH_RESULTS }),
  };
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderAutocomplete() {
  const oncomplete = vi.fn();
  const oncancel = vi.fn();
  const onfocusreturn = vi.fn();
  const result = render(WikilinkAutocomplete, { oncomplete, oncancel, onfocusreturn });
  return { ...result, oncomplete, oncancel, onfocusreturn };
}

function resetSearchLinkTargetsMock() {
  vi.mocked(searchLinkTargets).mockReset().mockResolvedValue({ results: SEARCH_RESULTS });
}

/** Wait for the fetchLinkTypes promise to resolve and populate the type picker. */
async function waitForTypes() {
  await vi.waitFor(() => {
    expect(screen.getByText('Title')).toBeInTheDocument();
  });
}

/**
 * Simulate a keydown forwarded from the parent textarea.
 *
 * WikilinkAutocomplete's type-picker stage doesn't listen for keyboard events
 * on its own DOM — the parent (MarkdownTextArea) captures textarea keydowns
 * and calls the exported `handleExternalKeydown` method. We replicate that
 * pattern here by calling the method on the component instance.
 *
 * Returns the KeyboardEvent so callers can assert on `defaultPrevented`.
 */
function sendExternalKeydown(
  component: ReturnType<typeof render>['component'],
  key: string,
  opts: KeyboardEventInit = {},
): KeyboardEvent {
  const event = new KeyboardEvent('keydown', { key, cancelable: true, ...opts });
  flushSync(() => {
    component.handleExternalKeydown(event);
  });
  return event;
}

/** Render, wait for types, then transition to search stage for "Title". */
async function openSearch() {
  const ctx = renderAutocomplete();
  await waitForTypes();

  sendExternalKeydown(ctx.component, 'Enter');
  await vi.waitFor(() => {
    expect(screen.getByRole('combobox', { name: /search title/i })).toBeInTheDocument();
  });

  // Wait for initial search results
  await vi.waitFor(() => {
    expect(screen.getByText(SEARCH_RESULTS[0].label)).toBeInTheDocument();
  });

  const searchInput = screen.getByRole('combobox', { name: /search title/i });
  return { ...ctx, searchInput };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('WikilinkAutocomplete', () => {
  afterEach(() => {
    // Reset to default mock — mockResolvedValueOnce overrides persist until implementation reset.
    resetSearchLinkTargetsMock();
  });

  // -----------------------------------------------------------------------
  // Type picker stage
  // -----------------------------------------------------------------------

  it('renders the type picker with link type options', async () => {
    renderAutocomplete();
    await waitForTypes();

    expect(screen.getByText('Insert link')).toBeInTheDocument();
    expect(screen.getByText('Title')).toBeInTheDocument();
    expect(screen.getByText('Manufacturer')).toBeInTheDocument();
    expect(screen.getByText('Citation')).toBeInTheDocument();
  });

  it('highlights items with ArrowDown/ArrowUp keyboard navigation', async () => {
    const { component } = renderAutocomplete();
    await waitForTypes();

    // First item starts highlighted
    const options = screen.getAllByRole('option');
    expect(options[0]).toHaveAttribute('aria-selected', 'true');

    // ArrowDown moves to second
    sendExternalKeydown(component, 'ArrowDown');
    expect(options[0]).toHaveAttribute('aria-selected', 'false');
    expect(options[1]).toHaveAttribute('aria-selected', 'true');

    // ArrowUp moves back to first
    sendExternalKeydown(component, 'ArrowUp');
    expect(options[0]).toHaveAttribute('aria-selected', 'true');
    expect(options[1]).toHaveAttribute('aria-selected', 'false');
  });

  it('clamps ArrowDown at the last item', async () => {
    const { component } = renderAutocomplete();
    await waitForTypes();

    const options = screen.getAllByRole('option');

    // Press ArrowDown past the end
    sendExternalKeydown(component, 'ArrowDown');
    sendExternalKeydown(component, 'ArrowDown');
    sendExternalKeydown(component, 'ArrowDown'); // past last (3 items)

    expect(options[2]).toHaveAttribute('aria-selected', 'true');
  });

  it('clamps ArrowUp at the first item', async () => {
    const { component } = renderAutocomplete();
    await waitForTypes();

    const options = screen.getAllByRole('option');

    // Already on first item — ArrowUp should stay
    sendExternalKeydown(component, 'ArrowUp');
    expect(options[0]).toHaveAttribute('aria-selected', 'true');
  });

  it('prevents default on ArrowDown/ArrowUp/Enter', async () => {
    const { component } = renderAutocomplete();
    await waitForTypes();

    const down = sendExternalKeydown(component, 'ArrowDown');
    expect(down.defaultPrevented).toBe(true);

    const up = sendExternalKeydown(component, 'ArrowUp');
    expect(up.defaultPrevented).toBe(true);

    const enter = sendExternalKeydown(component, 'Enter');
    expect(enter.defaultPrevented).toBe(true);
  });

  it('transitions to search stage on Enter', async () => {
    const { component } = renderAutocomplete();
    await waitForTypes();

    sendExternalKeydown(component, 'Enter');

    await vi.waitFor(() => {
      expect(screen.getByRole('combobox', { name: /search title/i })).toBeInTheDocument();
    });
  });

  it('transitions to search stage on mouse click', async () => {
    const user = userEvent.setup();
    renderAutocomplete();
    await waitForTypes();

    const titleOption = screen.getAllByRole('option')[0];
    await user.click(titleOption);

    await vi.waitFor(() => {
      expect(screen.getByRole('combobox', { name: /search title/i })).toBeInTheDocument();
    });
  });

  it('fires oncancel on Escape', async () => {
    const { component, oncancel } = renderAutocomplete();
    await waitForTypes();

    const event = sendExternalKeydown(component, 'Escape');

    expect(oncancel).toHaveBeenCalledOnce();
    expect(event.defaultPrevented).toBe(true);
  });

  // -----------------------------------------------------------------------
  // Back-navigation from search stage
  // -----------------------------------------------------------------------

  it('goes back to type picker on Backspace when search input is empty', async () => {
    const user = userEvent.setup();
    const { searchInput } = await openSearch();

    await user.click(searchInput);
    await user.keyboard('{Backspace}');

    expect(screen.getByText('Insert link')).toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: /search title/i })).not.toBeInTheDocument();
  });

  it('goes back to type picker on ArrowLeft at cursor position 0', async () => {
    const user = userEvent.setup();
    const { searchInput } = await openSearch();

    await user.click(searchInput);
    await user.keyboard('{ArrowLeft}');

    expect(screen.getByText('Insert link')).toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: /search title/i })).not.toBeInTheDocument();
  });

  it('preserves type highlight on back-navigation', async () => {
    const user = userEvent.setup();
    const { component } = renderAutocomplete();
    await waitForTypes();

    // Navigate to second type (Manufacturer) and select it
    sendExternalKeydown(component, 'ArrowDown');
    sendExternalKeydown(component, 'Enter');
    await vi.waitFor(() => {
      expect(screen.getByRole('combobox', { name: /search manufacturer/i })).toBeInTheDocument();
    });

    // Go back via Backspace on empty search
    const searchInput = screen.getByRole('combobox', { name: /search manufacturer/i });
    await user.click(searchInput);
    await user.keyboard('{Backspace}');

    // Previously selected type (Manufacturer) should still be highlighted
    const options = screen.getAllByRole('option');
    expect(options[0]).toHaveAttribute('aria-selected', 'false');
    expect(options[1]).toHaveAttribute('aria-selected', 'true');
  });

  it('calls onfocusreturn on back-navigation so parent can reclaim focus', async () => {
    const user = userEvent.setup();
    const { searchInput, onfocusreturn } = await openSearch();

    await user.click(searchInput);
    await user.keyboard('{Backspace}');

    expect(onfocusreturn).toHaveBeenCalledOnce();
  });

  // -----------------------------------------------------------------------
  // Search stage — results and selection
  // -----------------------------------------------------------------------

  it('shows "No matches" when search returns empty results', async () => {
    vi.mocked(searchLinkTargets).mockResolvedValueOnce({ results: [] });

    const { component } = renderAutocomplete();
    await waitForTypes();

    sendExternalKeydown(component, 'Enter');
    await vi.waitFor(() => {
      expect(screen.getByText('No matches')).toBeInTheDocument();
    });
  });

  it('calls oncomplete with formatted link text when a result is selected', async () => {
    const user = userEvent.setup();
    const { oncomplete, searchInput } = await openSearch();

    await user.click(searchInput);
    await user.keyboard('{ArrowDown}');
    await user.keyboard('{Enter}');

    expect(oncomplete).toHaveBeenCalledOnce();
    expect(oncomplete).toHaveBeenCalledWith(`[[title:${SEARCH_RESULTS[0].ref}]]`);
  });

  it('sets aria-activedescendant on the search input during keyboard navigation', async () => {
    const user = userEvent.setup();
    const { searchInput } = await openSearch();

    // No active descendant initially (searchIndex starts at -1)
    expect(searchInput).not.toHaveAttribute('aria-activedescendant');

    // ArrowDown highlights first result — read its id from the DOM
    await user.click(searchInput);
    await user.keyboard('{ArrowDown}');
    const options = screen.getAllByRole('option');
    expect(searchInput).toHaveAttribute('aria-activedescendant', options[0].id);

    // ArrowDown highlights second result
    await user.keyboard('{ArrowDown}');
    expect(searchInput).toHaveAttribute('aria-activedescendant', options[1].id);
  });

  // -----------------------------------------------------------------------
  // Debounce / timer behavior
  // -----------------------------------------------------------------------

  describe('debounce behavior', () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    /** Transition to search stage using fake timers. */
    async function enterSearchStage() {
      const { component } = renderAutocomplete();

      await vi.advanceTimersByTimeAsync(0);
      await vi.waitFor(() => {
        expect(screen.getByText('Title')).toBeInTheDocument();
      });

      sendExternalKeydown(component, 'Enter');
      // Flush the microtask from the synchronous empty-query search
      await vi.advanceTimersByTimeAsync(0);
      await vi.waitFor(() => {
        expect(screen.getByRole('combobox', { name: /search title/i })).toBeInTheDocument();
      });

      // Reset the mock fully so the debounce tests start from the default implementation
      // without inheriting any one-off overrides.
      resetSearchLinkTargetsMock();

      return screen.getByRole('combobox', { name: /search title/i });
    }

    it('fires search immediately for empty query', async () => {
      const { component } = renderAutocomplete();
      await vi.advanceTimersByTimeAsync(0);
      await vi.waitFor(() => {
        expect(screen.getByText('Title')).toBeInTheDocument();
      });

      // selectType calls debouncedSearch.search('') — fires synchronously
      sendExternalKeydown(component, 'Enter');
      await vi.advanceTimersByTimeAsync(0);

      expect(vi.mocked(searchLinkTargets)).toHaveBeenCalledWith('title', '');
    });

    // Debounce timing mechanics (exact delay, coalescing) are covered by
    // search-helpers.test.ts. Here we verify the UI-visible outcome:
    // typing in the search input eventually fetches with the typed query.
    it('typing in search input fetches results for the query', async () => {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      const input = await enterSearchStage();

      await user.click(input);
      await user.keyboard('mars');
      await vi.advanceTimersByTimeAsync(200);

      expect(vi.mocked(searchLinkTargets)).toHaveBeenCalledWith('title', 'mars');
    });

    it('discards stale responses when a newer search resolves first', async () => {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      const input = await enterSearchStage();

      const slowResults = [{ ref: 'slow', label: 'Slow Result' }];
      const fastResults = [{ ref: 'fast', label: 'Fast Result' }];

      // First call resolves slowly, second resolves immediately
      vi.mocked(searchLinkTargets)
        .mockImplementationOnce(
          () => new Promise((resolve) => setTimeout(() => resolve({ results: slowResults }), 500)),
        )
        .mockImplementationOnce(() => Promise.resolve({ results: fastResults }));

      // Type 'a' and let the debounce fire (200ms)
      await user.click(input);
      await user.keyboard('a');
      await vi.advanceTimersByTimeAsync(200);

      // Type 'b' (clears + retypes), let debounce fire
      await user.keyboard('b');
      await vi.advanceTimersByTimeAsync(200);

      // Fast response resolves immediately
      await vi.advanceTimersByTimeAsync(0);

      // Advance past the slow response
      await vi.advanceTimersByTimeAsync(500);

      // Only the fast results should be displayed — slow response was stale
      await vi.waitFor(() => {
        expect(screen.getByText('Fast Result')).toBeInTheDocument();
      });
      expect(screen.queryByText('Slow Result')).not.toBeInTheDocument();
    });
  });
});
