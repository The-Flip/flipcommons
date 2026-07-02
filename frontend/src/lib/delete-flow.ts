/**
 * Generic client shim for catalog soft-delete endpoints.
 *
 * Title, Model, and Person (and every future lifecycle entity) all hit a
 * ``POST /api/{collection}/{public_id}/delete/`` endpoint with the same request
 * body shape and the same 200 / 422 / 429 response taxonomy. The only
 * per-entity variations are the endpoint path and the typed success body,
 * so this module owns the shared classification and each entity's
 * ``{entity}-delete.ts`` binds a typed ``submitDelete`` via
 * :func:`createDeleteSubmitter`.
 */
import client from '$lib/api/client';
import { parseApiError } from '$lib/api/parse-api-error';
import type { BlockingReferrerSchema, paths } from '$lib/api/schema';
import type { EditCitationSelection } from '$lib/edit-citation';
import { buildEditCitationsRequest } from '$lib/edit-citation';

export type BlockingReferrer = BlockingReferrerSchema;

export type DeleteOutcome<TResponse> =
  | { kind: 'ok'; data: TResponse }
  | { kind: 'rate_limited'; retryAfterSeconds: number; message: string }
  | {
      kind: 'blocked';
      blockedBy: BlockingReferrer[];
      message: string;
      // Escape hatch for entity-specific fields the 422 body may carry
      // (e.g. Person's ``active_credit_count``). Entries not emitted by
      // the backend are simply absent.
      extra: Record<string, unknown>;
    }
  | { kind: 'form_error'; message: string };

interface DeleteSubmitOptions {
  note?: string;
  citation?: EditCitationSelection | null;
}

// Entity-segment union derived from the schema's delete routes.
// New linkable entities pick this up automatically when codegen runs.
type DeleteEntity =
  Extract<
    keyof paths,
    `/api/${string}/{public_id}/delete/`
  > extends `/api/${infer E}/{public_id}/delete/`
    ? E
    : never;

type DeleteResponse<E extends DeleteEntity> = paths[`/api/${E}/{public_id}/delete/`] extends {
  post: { responses: { 200: { content: { 'application/json': infer R } } } };
}
  ? R
  : never;

export function createDeleteSubmitter<E extends DeleteEntity>(entity: E) {
  const endpoint = `/api/${entity}/{public_id}/delete/`;
  return async (
    public_id: string,
    opts: DeleteSubmitOptions = {},
  ): Promise<DeleteOutcome<DeleteResponse<E>>> => {
    // openapi-fetch can't resolve a typed body for a path it sees as a
    // dynamic string, so the casts are localized here. `entity` is
    // statically constrained to DeleteEntity at the call site.
    const { data, error, response } = await client.POST(
      endpoint as never,
      {
        params: { path: { public_id } },
        body: {
          note: opts.note ?? '',
          citations: buildEditCitationsRequest(opts.citation ?? null),
        },
      } as never,
    );

    if (response.status === 429) {
      const retryAfter = Number(response.headers.get('Retry-After') ?? '86400');
      const hours = Math.max(1, Math.round(retryAfter / 3600));
      return {
        kind: 'rate_limited',
        retryAfterSeconds: retryAfter,
        message: `You've reached the delete limit. Try again in about ${hours} hour${hours === 1 ? '' : 's'}.`,
      };
    }

    if (response.status === 422) {
      const body = (await response
        .clone()
        .json()
        .catch(() => null)) as
        | ({ blocked_by?: BlockingReferrer[]; detail?: unknown } & Record<string, unknown>)
        | null;
      if (body && Array.isArray(body.blocked_by)) {
        const { blocked_by, detail, ...extra } = body;
        return {
          kind: 'blocked',
          blockedBy: blocked_by,
          message:
            typeof detail === 'string'
              ? detail
              : 'Cannot delete: active references would be left dangling.',
          extra,
        };
      }
    }

    if (error || !data) {
      const parsed = parseApiError(error);
      return { kind: 'form_error', message: parsed.message || 'Could not delete record.' };
    }

    return { kind: 'ok', data: data as DeleteResponse<E> };
  };
}
