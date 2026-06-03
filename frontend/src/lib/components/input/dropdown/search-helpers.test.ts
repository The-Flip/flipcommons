import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { createDebouncedSearch, formatCitationResult } from './search-helpers';

describe('createDebouncedSearch', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('calls fetchFn immediately for empty query', async () => {
    const fetchFn = vi.fn().mockResolvedValue(['a', 'b']);
    const onResults = vi.fn();
    const search = createDebouncedSearch(fetchFn, onResults);

    search.search('');
    // Immediate — no timer needed
    await vi.advanceTimersByTimeAsync(0);

    expect(fetchFn).toHaveBeenCalledWith('');
    expect(onResults).toHaveBeenCalledWith(['a', 'b']);
  });

  it('debounces non-empty queries by the specified delay', async () => {
    const fetchFn = vi.fn().mockResolvedValue(['x']);
    const onResults = vi.fn();
    const search = createDebouncedSearch(fetchFn, onResults, 200);

    search.search('hello');

    // Not called yet at 100ms
    await vi.advanceTimersByTimeAsync(100);
    expect(fetchFn).not.toHaveBeenCalled();

    // Called at 200ms
    await vi.advanceTimersByTimeAsync(100);
    expect(fetchFn).toHaveBeenCalledWith('hello');
    expect(onResults).toHaveBeenCalledWith(['x']);
  });

  it('discards stale responses when a newer search fires', async () => {
    let resolveFirst: (v: string[]) => void;
    let resolveSecond: (v: string[]) => void;
    const fetchFn = vi
      .fn()
      .mockImplementationOnce(() => new Promise((r) => (resolveFirst = r)))
      .mockImplementationOnce(() => new Promise((r) => (resolveSecond = r)));
    const onResults = vi.fn();
    const search = createDebouncedSearch(fetchFn, onResults, 200);

    // Fire first search
    search.search('ab');
    await vi.advanceTimersByTimeAsync(200);

    // Fire second search before first resolves
    search.search('abc');
    await vi.advanceTimersByTimeAsync(200);

    // Resolve second first, then first
    resolveSecond!(['second']);
    await vi.advanceTimersByTimeAsync(0);
    expect(onResults).toHaveBeenCalledWith(['second']);

    resolveFirst!(['first']);
    await vi.advanceTimersByTimeAsync(0);
    // onResults should NOT have been called again with the stale result
    expect(onResults).toHaveBeenCalledTimes(1);
  });

  it('cancels pending search and ignores in-flight responses', async () => {
    let resolveFn: (v: string[]) => void;
    const fetchFn = vi.fn().mockImplementation(() => new Promise((r) => (resolveFn = r)));
    const onResults = vi.fn();
    const search = createDebouncedSearch(fetchFn, onResults, 200);

    search.search('query');
    await vi.advanceTimersByTimeAsync(200);
    expect(fetchFn).toHaveBeenCalled();

    // Cancel before resolve
    search.cancel();
    resolveFn!(['late']);
    await vi.advanceTimersByTimeAsync(0);
    expect(onResults).not.toHaveBeenCalled();
  });

  it('cancel prevents a pending debounced search from firing', async () => {
    const fetchFn = vi.fn().mockResolvedValue([]);
    const onResults = vi.fn();
    const search = createDebouncedSearch(fetchFn, onResults, 200);

    search.search('query');
    await vi.advanceTimersByTimeAsync(100);
    search.cancel();
    await vi.advanceTimersByTimeAsync(200);

    expect(fetchFn).not.toHaveBeenCalled();
  });

  it('resets debounce timer when search is called again', async () => {
    const fetchFn = vi.fn().mockResolvedValue(['result']);
    const onResults = vi.fn();
    const search = createDebouncedSearch(fetchFn, onResults, 200);

    search.search('a');
    await vi.advanceTimersByTimeAsync(150);
    search.search('ab');
    await vi.advanceTimersByTimeAsync(150);

    // Only 150ms since second call — not fired yet
    expect(fetchFn).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(50);
    expect(fetchFn).toHaveBeenCalledTimes(1);
    expect(fetchFn).toHaveBeenCalledWith('ab');
  });

  it('uses default delay of 200ms', async () => {
    const fetchFn = vi.fn().mockResolvedValue([]);
    const onResults = vi.fn();
    const search = createDebouncedSearch(fetchFn, onResults);

    search.search('test');
    await vi.advanceTimersByTimeAsync(199);
    expect(fetchFn).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(1);
    expect(fetchFn).toHaveBeenCalled();
  });
});

describe('formatCitationResult', () => {
  it('formats name only', () => {
    expect(formatCitationResult({ name: 'A Book', author: '', year: null })).toBe('A Book');
  });

  it('formats name + author', () => {
    expect(formatCitationResult({ name: 'A Book', author: 'John Doe', year: null })).toBe(
      'A Book \u2014 John Doe',
    );
  });

  it('formats name + year', () => {
    expect(formatCitationResult({ name: 'A Book', author: '', year: 1996 })).toBe(
      'A Book \u2014 1996',
    );
  });

  it('formats name + author + year', () => {
    expect(formatCitationResult({ name: 'A Book', author: 'John Doe', year: 1996 })).toBe(
      'A Book \u2014 John Doe, 1996',
    );
  });
});
