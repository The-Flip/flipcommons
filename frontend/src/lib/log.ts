/**
 * Structured logging for the Node SSR process.
 *
 * Railway reads a JSON line's own `level`, and classifies plain text by the
 * stream instead — stdout `info`, stderr `error`. Node writes `console.warn` to
 * stderr alongside `console.error`, so an unstructured SSR warning is
 * indistinguishable from a fault. Field names match `RailwayJSONFormatter`
 * (backend/config/log_format.py) so one Railway query spans both processes.
 *
 * No `pid`, though the backend emits one: its absence is how
 * `railway_lines.emitter` tells an SSR line from a Python one.
 */

/** Railway's severity vocabulary. Mirrors `railway_level()` on the backend. */
export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

/**
 * Railway's log store has no scrubbing, so an attribute is published verbatim —
 * keep personal data out (docs/Observability.md). Scalars are also the only
 * thing it can index.
 */
export type LogAttribute = string | number | boolean | null;

export type LogOptions = {
  /** Folded into `message`, so a stack is one log event and not one row per frame. */
  cause?: unknown;
  /** Filterable Railway attributes. */
  attributes?: Readonly<Record<string, LogAttribute>>;
};

export type Logger = {
  [Level in LogLevel]: (message: string, options?: LogOptions) => void;
};

/** Build-time constant, so each bundle keeps only its own branch. */
const EMIT_JSON = import.meta.env.SSR && !import.meta.env.DEV;

/** Render one log event as the JSON line Railway parses. */
export function railwayLogLine(
  name: string,
  level: LogLevel,
  message: string,
  options: LogOptions = {},
): string {
  // Attributes first: the fields below must win a name collision, or an
  // attribute could rewrite the severity Railway reads.
  return JSON.stringify({
    ...options.attributes,
    level,
    message: foldCause(message, options.cause),
    logger: name,
    time: new Date().toISOString(),
  });
}

function foldCause(message: string, cause: unknown): string {
  if (cause === undefined) return message;
  return `${message}\n${renderCause(cause)}`;
}

/**
 * Rendering an `unknown` is fallible — a null-prototype object has no
 * `toString`. A logger that throws inside an error handler propagates in place
 * of the error it was reporting, so an unrenderable cause costs only its text.
 */
function renderCause(cause: unknown): string {
  try {
    // `String()` rather than interpolation, which throws on a symbol.
    return cause instanceof Error
      ? (cause.stack ?? `${cause.name}: ${cause.message}`)
      : String(cause);
  } catch {
    return '[cause could not be rendered]';
  }
}

/**
 * @param name becomes the `logger` field in JSON and the `[name]` console prefix.
 * Name it after the module, like `getLogger(__name__)` on the backend, so a line in
 * Railway points at the code that wrote it.
 */
export function getLogger(name: string): Logger {
  const emit = (level: LogLevel, message: string, options?: LogOptions): void => {
    if (EMIT_JSON) {
      // stderr at every level: the JSON `level` decides severity, so which
      // stream carried it stops mattering.
      process.stderr.write(`${railwayLogLine(name, level, message, options)}\n`);
      return;
    }
    // Console off the server and in dev: devtools beat a JSON string there.
    const line = `[${name}] ${message}`;
    const args: unknown[] = options?.cause === undefined ? [line] : [line, options.cause];
    // eslint-disable-next-line no-restricted-syntax -- the sink the rule points callers at
    console[level](...args);
  };
  return {
    debug: (message, options) => emit('debug', message, options),
    info: (message, options) => emit('info', message, options),
    warn: (message, options) => emit('warn', message, options),
    error: (message, options) => emit('error', message, options),
  };
}
