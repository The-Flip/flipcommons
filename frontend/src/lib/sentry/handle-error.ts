import type { HandleClientError, HandleServerError } from '@sveltejs/kit';
import { getLogger } from '$lib/log';

// SvelteKit's `handleError` hook is called for every unexpected error
// during a request, including the SvelteKitError(404) thrown by prerender's
// link-discovery crawl over `/api/*` preload hints. It is not called for
// errors thrown via `error()`: SvelteKit serializes that HttpError straight
// to the client, so a fault thrown that way is never logged or captured.
// We pass these handlers to Sentry.handleErrorWithSentry(...) so Sentry's
// defaultErrorHandler (which dumps a full stack for every error, 4xx
// included) is never used.
//
// 4xx: log a single line at info level. A 4xx is an expected request
//      outcome (the server correctly said "not here" / "not allowed"),
//      not a server fault, so it should not surface as severity=error in
//      log aggregators. Stacks are pure noise — Sentry already filters
//      these out of captureException.
// 5xx: log the line plus the stack at error level. Sentry has the
//      structured event; the stack in the container logs gives operators
//      immediate context to grep Sentry by.
//
// `status` rides along as a log attribute so Railway can filter on it
// directly, rather than only through a substring match on the message.

const log = getLogger('handle-error');

export const handleServerError: HandleServerError = ({ error, status, event }) => {
  const code = status ?? 500;
  const line = `[${code}] ${event.request.method} ${event.url.pathname}`;
  if (code >= 400 && code < 500) {
    log.info(line, { attributes: { status: code } });
    return;
  }
  log.error(line, { cause: error, attributes: { status: code } });
};

export const handleClientError: HandleClientError = ({ error, status, message }) => {
  const code = status ?? 500;
  const line = `[${code}] ${message}`;
  if (code >= 400 && code < 500) {
    log.info(line, { attributes: { status: code } });
    return;
  }
  log.error(line, { cause: error, attributes: { status: code } });
};
