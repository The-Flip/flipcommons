/**
 * Shared machinery for the per-family filter codecs (`games.ts`,
 * `manufacturers.ts`): the param-spec types, the generic parse/serialize
 * walkers over a param declaration, and the numeric coercion guard. No Svelte
 * imports — framework-agnostic and testable.
 */

/** One single-value URL param and how it reads/writes filter state `F`. */
export type SingleParamSpec<F> = {
  multi?: false;
  get: (f: F) => string | null;
  set: (f: F, v: string) => void;
};

/** One repeated URL param (`theme=a&theme=b`) and how it reads/writes `F`. */
export type MultiParamSpec<F> = {
  multi: true;
  get: (f: F) => string[];
  set: (f: F, v: string[]) => void;
};

export type ParamSpec<F> = SingleParamSpec<F> | MultiParamSpec<F>;

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

/**
 * Read filter state from URL search params into `empty` (mutates and returns
 * it). Params outside the declaration are ignored as noise (`utm_source`).
 */
export function parseParams<F>(
  sp: URLSearchParams,
  empty: F,
  specs: Record<string, ParamSpec<F>>,
): F {
  for (const [param, spec] of Object.entries(specs)) {
    if (spec.multi) {
      const vs = sp.getAll(param).filter(Boolean);
      if (vs.length > 0) spec.set(empty, vs);
    } else {
      const v = sp.get(param);
      if (v != null) spec.set(empty, v);
    }
  }
  return empty;
}

/**
 * Write filter state to a fresh URLSearchParams, in the declaration's param
 * order (which makes the serialization canonical: equal states produce equal
 * strings).
 */
export function serializeParams<F>(f: F, specs: Record<string, ParamSpec<F>>): URLSearchParams {
  const sp = new URLSearchParams();
  for (const [param, spec] of Object.entries(specs)) {
    if (spec.multi) {
      for (const v of spec.get(f)) sp.append(param, v);
    } else {
      const v = spec.get(f);
      if (v != null) sp.set(param, v);
    }
  }
  return sp;
}
