/**
 * Shared machinery for the per-family filter codecs (`games.ts`,
 * `manufacturers.ts`): the param-kind declaration types, the generic
 * parse/serialize walkers over a declaration, the API-query empties strip and
 * the numeric coercion guard. No Svelte imports — framework-agnostic and
 * testable.
 */

/** A filter-state field's value: the three wire shapes a param can carry. */
export type ParamValue = string | number | null | string[];

/**
 * How one URL param reads and writes: a string scalar, a numeric scalar, or a
 * repeated param (`theme=a&theme=b`).
 */
export type ParamKind = 'string' | 'number' | 'multi';

/**
 * The kind a field's type forces: `string[]` fields are `multi`, numeric
 * fields are `number`, string fields are `string` — so declaring the wrong
 * kind for a field is a compile error. (Tuple-wrapped to keep the conditional
 * from distributing over `string | null` unions.)
 */
export type KindOf<T> = [T] extends [string[]]
  ? 'multi'
  : [T] extends [number | null]
    ? 'number'
    : 'string';

/**
 * A filter family's param declaration: every wire param's kind, keyed and
 * kind-checked against the state shape `F`.
 */
export type ParamKinds<F> = { [K in keyof F]: KindOf<F[K]> };

/**
 * A filter family's URL codec: committed filter state ⇄ the URL's search
 * params. `canonical` is the equality token — two states describe the same
 * filter iff their canonical strings match.
 */
export interface FilterCodec<F> {
  parse: (sp: URLSearchParams) => F;
  serialize: (f: F) => URLSearchParams;
  canonical: (f: F) => string;
}

/**
 * Every key of `T` made required, with `undefined` allowed as a value — the
 * shape of a fully-enumerated API query object: forgetting a newly added
 * schema field is a compile error, but an absent value stays expressible.
 * (Two steps because `-?` in a mapped type strips `undefined` from the
 * property type even when unioned explicitly.)
 */
export type Complete<T> = { [K in keyof Required<T>]: Required<T>[K] | undefined };

/**
 * Parse a numeric URL param, falling back to null on non-finite input (e.g. a
 * hand-edited `?year_min=abc`) so no reader seeds `NaN`.
 */
export function toNum(v: string): number | null {
  if (v.trim() === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

// The walkers widen the state to `Record<string, ParamValue>` internally: the
// declaration's kinds are compile-checked against each field's type, so the
// per-kind reads and writes below cannot put the wrong shape in a field.

/**
 * Read filter state from URL search params into `empty` (mutates and returns
 * it). Params outside the declaration are ignored as noise (`utm_source`).
 */
export function parseParams<F extends Record<string, ParamValue>>(
  sp: URLSearchParams,
  empty: F,
  kinds: ParamKinds<F>,
): F {
  const f: Record<string, ParamValue> = empty;
  for (const [param, kind] of Object.entries<ParamKind>(kinds)) {
    if (kind === 'multi') {
      const vs = sp.getAll(param).filter(Boolean);
      if (vs.length > 0) f[param] = vs;
    } else {
      const v = sp.get(param);
      if (v != null) f[param] = kind === 'number' ? toNum(v) : v;
    }
  }
  return empty;
}

/**
 * Write filter state to a fresh URLSearchParams, in the declaration's param
 * order (which makes the serialization canonical: equal states produce equal
 * strings). Absent values — `null`, the empty string, the empty array —
 * serialize to nothing.
 */
export function serializeParams<F extends Record<string, ParamValue>>(
  f: F,
  kinds: ParamKinds<F>,
): URLSearchParams {
  const sp = new URLSearchParams();
  for (const [param, kind] of Object.entries<ParamKind>(kinds)) {
    const v: ParamValue = f[param];
    if (kind === 'multi') {
      for (const x of v as string[]) sp.append(param, x);
    } else if (v != null && v !== '') {
      sp.set(param, String(v));
    }
  }
  return sp;
}

/**
 * Project parsed filter state onto an API query object: absent values —
 * `null`, the empty string, the empty array — become `undefined` so the typed
 * client omits them from the request.
 */
export function stripEmpties<F extends Record<string, ParamValue>>(
  f: F,
): { [K in keyof F]: Exclude<F[K], null> | undefined } {
  const out: Record<string, ParamValue | undefined> = {};
  for (const [k, v] of Object.entries(f)) {
    out[k] = v == null || v === '' || (Array.isArray(v) && v.length === 0) ? undefined : v;
  }
  return out as { [K in keyof F]: Exclude<F[K], null> | undefined };
}

/**
 * A one-field filter patch built by indexed assignment, so a union-typed
 * `field` stays type-checked against its value (an object literal with a
 * computed key would widen to a string index signature).
 */
export function fieldPatch<F, K extends keyof F>(field: K, value: F[K]): Partial<F> {
  const patch: Partial<F> = {};
  patch[field] = value;
  return patch;
}

/**
 * Whether any structured filter is active — every field **except** the
 * free-text `q`. The per-family `hasActive*` exports put a name and a doc on
 * this for their consumers.
 */
export function hasActiveParams<F extends Record<string, ParamValue>>(f: F): boolean {
  return Object.entries(f).some(
    ([param, v]) => param !== 'q' && v != null && v !== '' && (!Array.isArray(v) || v.length > 0),
  );
}
