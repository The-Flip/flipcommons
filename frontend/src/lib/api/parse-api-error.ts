/**
 * Parse backend API error responses into a human-readable message and
 * per-field error map. Shared across every save / delete / create flow.
 */

import type {
  PolicyDeniedBodySchema,
  RateLimitErrorBodySchema,
  ValidationErrorBodySchema,
} from './schema';

export type FieldErrors = Record<string, string>;

type ParsedError = { message: string; fieldErrors: FieldErrors };

/**
 * Wire shape of any structured error body. Mirrors the backend's
 * `StructuredErrorBodySchema` base in `apps/core/schemas.py`: every
 * variant carries `{ kind, message }`, plus optional variant fields.
 *
 * Enumerated rather than expressed as "any subtype of the base"
 * because TypeScript collapses `Specific | { kind: string; message:
 * string }` to the wider variant — we'd lose narrowing for the
 * special case (`validation_error`). A new backend error kind only
 * needs to appear here if it requires custom parsing (field-level
 * errors, retry hints, etc.); kinds that render via the base
 * `message` alone fall through and need no addition.
 */
type StructuredErrorBody =
  ValidationErrorBodySchema | RateLimitErrorBodySchema | PolicyDeniedBodySchema;

function isStructuredErrorBody(value: unknown): value is StructuredErrorBody {
  if (typeof value !== 'object' || value === null) return false;
  const v = value as { kind?: unknown; message?: unknown };
  return typeof v.kind === 'string' && typeof v.message === 'string';
}

function plain(message: string): ParsedError {
  return { message, fieldErrors: {} };
}

/**
 * Structured error bodies share a base contract from
 * `StructuredErrorBodySchema` in `backend/apps/core/schemas.py`: every
 * variant carries `{ kind, message, ...variant_fields }`. The default
 * extraction is `message` — only variants that need richer parsing
 * (field-level errors, etc.) get a special case.
 *
 * Today the only special case is `validation_error`, which produces a
 * field-level error map alongside the message. `rate_limit`,
 * `policy_denied`, and any future variant fall through to the base
 * `message` field — adding a new structured error on the backend
 * requires no change here unless it has fields beyond the base.
 *
 * Plain-string `detail` from `HttpError(...)` and stock Ninja 401/404/etc.
 * remains supported as the unstructured fallback. Anything that fails
 * the structured-body shape check (raw arrays, missing `kind`) falls
 * through to `JSON.stringify` — surfacing a backend/frontend mismatch
 * loudly rather than rendering garbage.
 */
export function parseApiError(error: unknown): ParsedError {
  if (typeof error === 'object' && error !== null && 'detail' in error) {
    const { detail } = error as { detail: unknown };

    if (typeof detail === 'string') return plain(detail);

    if (isStructuredErrorBody(detail)) {
      if (detail.kind === 'validation_error') {
        const { field_errors, form_errors, message } = detail;
        const parts = [
          ...form_errors,
          ...Object.entries(field_errors).map(([k, v]) => `${k}: ${v}`),
        ];
        return {
          message: parts.length > 0 ? parts.join(' ') : message,
          fieldErrors: field_errors,
        };
      }
      // Every non-validation variant of StructuredErrorBody inherits
      // `{ kind, message }` from `StructuredErrorBodySchema`; the base
      // contract is what makes this fall-through type-safe.
      return plain(detail.message);
    }

    // `detail` is something other than a string or a structured body —
    // a raw array (the legacy Pydantic shape), an object missing `kind`,
    // etc. Fall through to the bottom-of-function JSON.stringify so the
    // whole envelope is surfaced loudly instead of rendering empty.
  }

  if (typeof error === 'string') return plain(error);
  return plain(JSON.stringify(error));
}
