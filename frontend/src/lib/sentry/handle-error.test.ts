import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { handleClientError, handleServerError } from './handle-error';

describe('handleServerError', () => {
  let errorSpy: ReturnType<typeof vi.spyOn>;
  let infoSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    infoSpy = vi.spyOn(console, 'info').mockImplementation(() => {});
  });

  afterEach(() => {
    errorSpy.mockRestore();
    infoSpy.mockRestore();
  });

  function fakeEvent(method: string, pathname: string) {
    return {
      request: { method },
      url: { pathname },
      // The full RequestEvent type has many more fields; the handler only
      // touches request.method and url.pathname so the rest is irrelevant.
    } as unknown as Parameters<typeof handleServerError>[0]['event'];
  }

  it('logs a single line for 4xx at info level with no stack trace', () => {
    const err = new Error('Not found: /api/foo');
    err.stack = 'Error: Not found: /api/foo\n    at frame1\n    at frame2';

    handleServerError({
      error: err,
      status: 404,
      message: 'Not Found',
      event: fakeEvent('GET', '/api/foo'),
    });

    // 4xx is an expected outcome, not a server fault — it must log at info,
    // not error, so log aggregators don't tag it as severity=error.
    expect(errorSpy).not.toHaveBeenCalled();
    expect(infoSpy).toHaveBeenCalledTimes(1);
    // No second argument at all: the error carrying the stack is never passed,
    // so no sink can reach the frames.
    expect(infoSpy.mock.calls[0]).toHaveLength(1);
    expect(infoSpy.mock.calls[0][0] as string).toContain('[404] GET /api/foo');
  });

  it('logs status line and stack for 5xx', () => {
    const err = new Error('boom');
    err.stack = 'Error: boom\n    at frame1';

    handleServerError({
      error: err,
      status: 500,
      message: 'Internal Error',
      event: fakeEvent('POST', '/api/bar'),
    });

    expect(errorSpy).toHaveBeenCalledTimes(1);
    expect(errorSpy.mock.calls[0][0] as string).toContain('[500] POST /api/bar');
    // The stack rides as the cause, which the console sink passes through and
    // the Railway sink folds into the JSON `message`.
    expect(errorSpy.mock.calls[0][1]).toBe(err);
  });

  it('treats undefined status as 5xx', () => {
    handleServerError({
      error: new Error('weird'),
      status: undefined as unknown as number,
      message: 'Unknown',
      event: fakeEvent('GET', '/api/baz'),
    });

    const logged = errorSpy.mock.calls[0][0] as string;
    expect(logged).toContain('[500] GET /api/baz');
  });
});

describe('handleClientError', () => {
  let errorSpy: ReturnType<typeof vi.spyOn>;
  let infoSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    infoSpy = vi.spyOn(console, 'info').mockImplementation(() => {});
  });

  afterEach(() => {
    errorSpy.mockRestore();
    infoSpy.mockRestore();
  });

  it('logs a single line for 4xx at info level with no stack trace', () => {
    const err = new Error('not found');
    err.stack = 'Error: not found\n    at frame1';

    handleClientError({
      error: err,
      status: 404,
      message: 'Not Found',
      event: {} as Parameters<typeof handleClientError>[0]['event'],
    });

    expect(errorSpy).not.toHaveBeenCalled();
    expect(infoSpy.mock.calls[0]).toHaveLength(1);
    expect(infoSpy.mock.calls[0][0] as string).toContain('[404] Not Found');
  });

  it('logs status line and stack for 5xx', () => {
    const err = new Error('boom');
    err.stack = 'Error: boom\n    at frame1';

    handleClientError({
      error: err,
      status: 500,
      message: 'Internal Error',
      event: {} as Parameters<typeof handleClientError>[0]['event'],
    });

    expect(errorSpy.mock.calls[0][0] as string).toContain('[500] Internal Error');
    expect(errorSpy.mock.calls[0][1]).toBe(err);
  });
});
