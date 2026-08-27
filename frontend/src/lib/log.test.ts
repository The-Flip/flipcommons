import { describe, expect, it } from 'vitest';
import { railwayLogLine } from './log';

// The sink choice (`EMIT_JSON`) is a build-time constant, so these cover the
// line Railway actually parses. Under vitest `import.meta.env.DEV` is true, so
// the console sink is the one every other test in the suite exercises.
describe('railwayLogLine', () => {
  function parse(...args: Parameters<typeof railwayLogLine>) {
    return JSON.parse(railwayLogLine(...args)) as Record<string, unknown>;
  }

  it('carries the level Railway reads instead of the stream', () => {
    expect(parse('sitemap', 'warn', 'route x unclassified').level).toBe('warn');
  });

  it('names the logger and stamps the time', () => {
    const line = parse('sitemap', 'info', 'hello');
    expect(line.logger).toBe('sitemap');
    expect(typeof line.time).toBe('string');
    expect(Number.isNaN(Date.parse(line.time as string))).toBe(false);
  });

  it('flattens attributes to top-level keys so Railway can filter on them', () => {
    expect(
      parse('handle-error', 'error', '[500] GET /x', { attributes: { status: 500 } }),
    ).toMatchObject({ status: 500, level: 'error' });
  });

  it('never lets an attribute rewrite the fields it owns', () => {
    const line = parse('x', 'error', 'boom', {
      attributes: { level: 'debug', message: 'spoofed', logger: 'elsewhere' },
    });
    expect(line.level).toBe('error');
    expect(line.message).toBe('boom');
    expect(line.logger).toBe('x');
  });

  it('folds a cause stack into the message so a crash is one log event', () => {
    const err = new Error('boom');
    err.stack = 'Error: boom\n    at frame1';
    const line = parse('x', 'error', '[500] POST /y', { cause: err });
    expect(line.message).toBe('[500] POST /y\nError: boom\n    at frame1');
    // One JSON line, however many frames the stack has.
    expect(railwayLogLine('x', 'error', '[500] POST /y', { cause: err })).not.toContain('\n');
  });

  it('folds a stackless Error by name and message', () => {
    const err = new Error('boom');
    err.stack = undefined;
    expect(parse('x', 'error', 'oops', { cause: err }).message).toBe('oops\nError: boom');
  });

  it('folds a non-Error cause without throwing', () => {
    expect(parse('x', 'error', 'oops', { cause: 'a string' }).message).toBe('oops\na string');
    expect(parse('x', 'error', 'oops', { cause: Symbol('s') }).message).toBe('oops\nSymbol(s)');
  });

  // An unrenderable cause must cost its own text, not the whole log line.
  it.each([
    ['a null-prototype object', Object.create(null) as unknown],
    [
      'a throwing toString',
      {
        toString: () => {
          throw new Error('hostile');
        },
      },
    ],
    [
      'a throwing Error getter',
      Object.create(Error.prototype, {
        stack: {
          get: () => {
            throw new Error('hostile');
          },
        },
      }) as unknown,
    ],
  ])('survives %s', (_label, cause) => {
    const line = parse('x', 'error', 'still logged', { cause });
    expect(line.message).toBe('still logged\n[cause could not be rendered]');
    expect(line.level).toBe('error');
  });

  it('omits the cause line entirely when there is none', () => {
    expect(parse('x', 'warn', 'plain').message).toBe('plain');
  });
});
