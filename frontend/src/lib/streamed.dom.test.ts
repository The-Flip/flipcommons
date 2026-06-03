import { render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, it, vi } from 'vitest';
import StreamedFixture from './streamed.fixture.svelte';

const status = () => screen.getByTestId('status').textContent;
const value = () => screen.getByTestId('value').textContent;

describe('streamed', () => {
  it('starts loading, then resolves to ready with the value', async () => {
    let resolve!: (v: string) => void;
    const promise = new Promise<string>((r) => (resolve = r));
    render(StreamedFixture, { promise });

    expect(status()).toBe('loading');
    expect(value()).toBe('');

    resolve('chicago');
    await vi.waitFor(() => expect(status()).toBe('ready'));
    expect(value()).toBe('chicago');
  });

  it('keeps the prior value while a new promise loads (sticky), then updates', async () => {
    const { rerender } = render(StreamedFixture, { promise: Promise.resolve('first') });
    await vi.waitFor(() => expect(value()).toBe('first'));

    // A "navigation": a fresh, still-pending promise replaces the old one.
    let resolveNext!: (v: string) => void;
    const next = new Promise<string>((r) => (resolveNext = r));
    await rerender({ promise: next });

    expect(status()).toBe('loading');
    expect(value()).toBe('first'); // sticky — old options stay visible

    resolveNext('second');
    await vi.waitFor(() => expect(value()).toBe('second'));
    expect(status()).toBe('ready');
  });

  it('drops an out-of-order earlier resolution (cancel guard)', async () => {
    let resolveSlow!: (v: string) => void;
    const slow = new Promise<string>((r) => (resolveSlow = r));
    const { rerender } = render(StreamedFixture, { promise: slow });

    // A later navigation resolves first.
    await rerender({ promise: Promise.resolve('fast') });
    await vi.waitFor(() => expect(value()).toBe('fast'));

    // The earlier (slow) promise now resolves — it must be ignored.
    resolveSlow('stale');
    await tick();
    expect(value()).toBe('fast');
    expect(status()).toBe('ready');
  });

  it('maps a resolved-undefined promise to error with no value', async () => {
    render(StreamedFixture, { promise: Promise.resolve(undefined) });
    await vi.waitFor(() => expect(status()).toBe('error'));
    expect(value()).toBe('');
  });
});
