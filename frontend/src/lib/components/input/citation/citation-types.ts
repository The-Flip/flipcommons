/** Types, pure helpers and the state-machine reducer for the citation flow. */
import type {
  CitationSourceChildSchema,
  CitationSourceSearchSchema,
  CitationExtractDraftSchema,
  CitationRecognitionSchema,
} from '$lib/api/schema';
import type { ApiClient } from '$lib/api/client';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type CitationSourceResult = CitationSourceSearchSchema;
export type ChildSource = CitationSourceChildSchema;
export type RecognitionResult = CitationRecognitionSchema;

/** Draft metadata returned by the extract endpoint (Open Library, etc.). */
export type ExtractionDraft = CitationExtractDraftSchema;

/** What seeds a create flow. The orchestrator routes a `web` seed (see
 *  `isWebSeed`) to the describe-site → page web flow and everything else to the
 *  authored-work form:
 *  - `name`: manual text — the authored-work form (type picker), unless a parent locks the type.
 *    `sourceType` preselects the picker (any citation-type key — the deliverer handoff sets it from
 *    the backend's `suggested_source_type`); `url` carries the pasted URL through flow state,
 *    deliberately unused today — the access-URL hedge, so threading it later is plumbing.
 *  - `extraction`: a scraped book draft (from an ISBN, pasted or extracted from a deliverer URL) —
 *    the authored-work form, fields prefilled.
 *  - `web`: a pasted web URL — the web flow. `siteName` non-null means the site already exists
 *    (Create Site is skipped, it names that site); null means a new site (Create Site shown). `draft`
 *    is the page scrape (page name + site name prefill, URL confirmed read-only) or null when the
 *    scrape failed/was skipped (URL stays editable, nothing prefilled). `pageName` prefills the page
 *    name when there's no scrape — used by the manual "add a page under a known site" path. */
export type CreateSeed =
  | { kind: 'name'; name: string; sourceType?: string; url?: string }
  | { kind: 'extraction'; draft: ExtractionDraft }
  | {
      kind: 'web';
      url: string;
      siteName: string | null;
      draft: ExtractionDraft | null;
      pageName?: string;
    };

/** Subset of a search result carried through the state machine after selecting an abstract source. */
export type ParentContext = {
  id: number;
  name: string;
  source_type: string;
  author: string;
  identifier_key: string;
};

/** An unsaved draft of a CitationInstance.  Accumulates across stages: search sets sourceId, identify may change it, the locator stage sets locator.
 *
 * `sourceType` keys the locator stage into the per-type behavior registry
 * (`$lib/citation-types`): placeholder, inline validation, canonical form.
 * `locatorHint` prefills the locator input (a pasted video URL's `t=` start
 * time, already formatted canonically by the backend) — it is deliberately
 * NOT `locator` so a hint is never mistaken for an entered locator. */
export type CitationInstanceDraft = {
  sourceId: number | null;
  sourceName: string;
  sourceType: string;
  locator: string;
  locatorHint: string;
  skipLocator: boolean;
};

/** A finished draft: the source is chosen (non-null) and the locator entered.
 * The flow hands this content spec to the consumer — nothing mints until
 * save. The quote is never collected here: both consumers offer it on a
 * revisitable surface (`EditCitationField`, the inline-citations panel),
 * editable until save. `sourceType` rides along so those surfaces can key
 * into the per-type locator metadata (`$lib/citation-types`) — a video cite's
 * locator field asks for a start time, a book's for a page. */
export type CompletedCitationDraft = {
  sourceId: number;
  sourceName: string;
  sourceType: string;
  locator: string;
};

/** What the citation flow calls on completion, with the finished content
 * spec. May return a promise (the inline flow reserves a `[[cite:slug]]`
 * slug from the backend before inserting its marker); a rejection keeps the
 * picker's final screen rendered with an error, so the user can retry. */
export type CitationCompletionHandler = (draft: CompletedCitationDraft) => void | Promise<void>;

/** Which stage the citation flow is in. Each variant carries only the context that stage needs. */
export type CiteState =
  /** Initial state. User searches for an existing source or pastes a URL. */
  | { stage: 'search'; draft: CitationInstanceDraft }
  /** User selected an abstract source and must identify which child to cite. */
  | {
      stage: 'identify';
      draft: CitationInstanceDraft;
      parent: ParentContext;
    }
  /** User is creating a new source. The seed carries what we know to prefill it.
   *  The orchestrator renders this stage with one of two create components: a
   *  web seed (see `isWebSeed`) gets the two-panel describe-site → page
   *  web flow; everything else gets the authored-work (book/magazine) form. */
  | {
      stage: 'create';
      draft: CitationInstanceDraft;
      parent: ParentContext | null;
      seed: CreateSeed;
    }
  /** Source is chosen. User refines the draft's optional locator (page
   *  number, start time, etc.). A skip-locator source skips this screen
   *  entirely.
   *
   *  `ready` marks completion: the reducer has everything it needs and the
   *  orchestrator should submit the draft. The stage stays `locator` rather
   *  than switching to a bare terminal because the completion handler can be
   *  async and fail (the inline flow's slug reservation POST) — the populated
   *  screen must stay rendered so a failure shows in place. `ready` is set
   *  with the stage never rendered at all for a skip-locator source. */
  | { stage: 'locator'; draft: CitationInstanceDraft; ready: boolean };

/** Inputs to the state machine, dispatched by stage components via the orchestrator. */
export type CiteAction =
  /** User picked a source from search results. Abstract → identify; concrete → locator. */
  | { type: 'source_selected'; source: CitationSourceResult }
  /** The exact citable CitationSource is known (via URL recognition, child selection, etc.). → locator. */
  | {
      type: 'source_identified';
      sourceId: number;
      sourceName: string;
      sourceType: string;
      skipLocator: boolean;
      locatorHint?: string;
    }
  /** User wants to create a new CitationSource. The seed says what prefill we have. → create. */
  | { type: 'create_started'; seed: CreateSeed }
  /** New CitationSource was created via API. → locator. */
  | {
      type: 'source_created';
      sourceId: number;
      sourceName: string;
      sourceType: string;
      skipLocator: boolean;
    }
  /** User submitted or skipped the locator stage. */
  | { type: 'locator_submitted'; locator: string };

// ---------------------------------------------------------------------------
// Pure functions
// ---------------------------------------------------------------------------

/** If *q* looks like a web URL — with or without a scheme — return it as a
 *  normalized `https://…` URL; otherwise null.
 *
 *  An already-schemed URL is returned verbatim (so a pasted `https://…` with an
 *  unencoded space still works as before). A scheme-less dotted host
 *  (`www.imdb.com/title/…`, `imdb.com`) gets `https://` prepended so the paste
 *  flow recognizes it. To avoid mistaking a plain search term for a URL, the
 *  scheme-less form requires no whitespace and a TLD-like final label (2+
 *  letters) — so `imdb.com` matches but `e.g` does not. A filename-shaped token
 *  like `notes.md` is an accepted false positive (rare in source search). */
export function urlFromQuery(q: string): string | null {
  const t = q.trim();
  if (!t) return null;
  if (/^https?:\/\//i.test(t)) return t;
  if (/\s/.test(t)) return null;
  return /^[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}(\/.*)?$/i.test(t) ? `https://${t}` : null;
}

/** Strip hyphens/spaces and return a 10/13-digit ISBN shape, or null.
 *  Shape-only, mirroring the backend's `normalize_isbn`: a hand-typed ISBN
 *  with a bad check digit still goes to Open Library to fail loudly. */
export function normalizeIsbn(raw: string): string | null {
  const stripped = raw.replace(/-/g, '').replace(/ /g, '').toUpperCase();
  if (stripped.length === 13 && /^\d{13}$/.test(stripped)) return stripped;
  if (stripped.length === 10 && /^\d{9}[\dX]$/.test(stripped)) return stripped;
  return null;
}

/** Whether a normalized 10/13-digit ISBN has a valid check digit. */
export function isbnChecksumOk(isbn: string): boolean {
  if (isbn.length === 10) {
    let total = 0;
    for (let i = 0; i < 10; i++) {
      const value = isbn[i] === 'X' ? 10 : Number(isbn[i]);
      total += (10 - i) * value;
    }
    return total % 11 === 0;
  }
  if (isbn.length === 13) {
    let total = 0;
    for (let i = 0; i < 13; i++) {
      total += Number(isbn[i]) * (i % 2 === 0 ? 1 : 3);
    }
    return total % 10 === 0;
  }
  return false;
}

/** An ISBN-shaped token inside free text, with optional space/hyphen
 *  separators, not butted against other alphanumerics. Candidates are
 *  checksum-gated below. Mirrors the backend's `_EMBEDDED_ISBN_RE`. */
const EMBEDDED_ISBN_RE =
  /(?<![0-9A-Za-z])(97[89][ -]?(?:\d[ -]?){9}\d|(?:\d[ -]?){9}[\dXx])(?![0-9A-Za-z])/g;

/** The ISBN a pasted query carries, or null — mirroring the backend's
 *  `classify_input` precedence: the whole input as an ISBN (shape-only, the
 *  lenient historical contract), never inside a URL (a digit run in a path is
 *  the deliverer classification's job), else a **checksum-valid** ISBN
 *  embedded anywhere in the text ("Pinball Compendium 978-0764325847 —
 *  first edition" still looks the book up). */
export function isbnFromQuery(q: string): string | null {
  const whole = normalizeIsbn(q);
  if (whole) return whole;
  if (urlFromQuery(q)) return null;
  for (const match of q.matchAll(EMBEDDED_ISBN_RE)) {
    const isbn = normalizeIsbn(match[1]);
    if (isbn && isbnChecksumOk(isbn)) return isbn;
  }
  return null;
}

/** The www-stripped, lowercased host of a URL, or `''` if it can't be parsed.
 *  Used to prefill the Site name when no `og:site_name` was scraped, so the
 *  field shows the name the new root will get. Mirrors the backend's
 *  `normalize_host`, which it falls back to (`name = site_name or host`). */
export function hostFromUrl(url: string): string {
  try {
    const host = new URL(url).hostname.toLowerCase();
    return host.startsWith('www.') ? host.slice(4) : host;
  } catch {
    return '';
  }
}

export function suppressChildResults(results: CitationSourceResult[]): CitationSourceResult[] {
  const resultIds = new Set(results.map((r) => r.id));
  return results.filter((r) => !r.parent_id || !resultIds.has(r.parent_id));
}

export function emptyDraft(): CitationInstanceDraft {
  return {
    sourceId: null,
    sourceName: '',
    sourceType: '',
    locator: '',
    locatorHint: '',
    skipLocator: false,
  };
}

// ---------------------------------------------------------------------------
// Child creation by identifier
// ---------------------------------------------------------------------------

export type CreateByIdentifierResult =
  | { ok: true; sourceId: number; sourceName: string; sourceType: string; skipLocator: boolean }
  | { ok: false; error: string };

/** Create (or reuse) a scheme child under a parent root using a structured
 *  identifier. The parent is the path param; the backend validates the
 *  identifier and owns the child's name and canonical URL. */
export async function createChildByIdentifier(
  apiClient: ApiClient,
  parentId: number,
  identifier: string,
): Promise<CreateByIdentifierResult> {
  const { data, error } = await apiClient.POST('/api/citation-sources/{source_id}/records/', {
    params: { path: { source_id: parentId } },
    body: { identifier },
  });
  if (error) {
    return { ok: false, error: typeof error === 'string' ? error : 'Invalid identifier.' };
  }
  return {
    ok: true,
    sourceId: data.id,
    sourceName: data.name,
    sourceType: data.source_type,
    skipLocator: data.skip_locator,
  };
}

// ---------------------------------------------------------------------------
// State machine
// ---------------------------------------------------------------------------

/** True when a create seed is a pasted web URL. The orchestrator renders these
 *  with the describe-site → page web flow; everything else (manual names,
 *  book/magazine extractions) uses the authored-work create form. */
export function isWebSeed(seed: CreateSeed): boolean {
  return seed.kind === 'web';
}

export function parentContextFromSource(source: CitationSourceResult): ParentContext {
  return {
    id: source.id,
    name: source.name,
    source_type: source.source_type,
    author: source.author,
    identifier_key: source.identifier_key,
  };
}

/** Invalid action/state combos return current state unchanged.
 *
 * The reducer owns stage sequencing end to end — including the skip-locator
 * shortcut and flow completion (the `ready` marker on the locator state) — so
 * the orchestrator submits exactly when told, never by sniffing the draft. */
export function transition(state: CiteState, action: CiteAction): CiteState {
  switch (action.type) {
    case 'source_selected': {
      if (state.stage !== 'search') return state;
      const draft = {
        ...state.draft,
        sourceId: action.source.id,
        sourceName: action.source.name,
        sourceType: action.source.source_type,
      };
      if (action.source.is_abstract) {
        return {
          stage: 'identify',
          draft: { ...draft, skipLocator: action.source.skip_locator },
          parent: parentContextFromSource(action.source),
        };
      }
      return {
        stage: 'locator',
        draft: { ...draft, skipLocator: action.source.skip_locator },
        ready: action.source.skip_locator,
      };
    }

    case 'source_identified': {
      if (state.stage !== 'search' && state.stage !== 'identify') return state;
      return {
        stage: 'locator',
        draft: {
          ...state.draft,
          sourceId: action.sourceId,
          sourceName: action.sourceName,
          sourceType: action.sourceType,
          skipLocator: action.skipLocator,
          locatorHint: action.locatorHint ?? '',
        },
        ready: action.skipLocator,
      };
    }

    case 'create_started': {
      if (state.stage !== 'search' && state.stage !== 'identify') return state;
      return {
        stage: 'create',
        draft: state.draft,
        parent: state.stage === 'identify' ? state.parent : null,
        seed: action.seed,
      };
    }

    case 'source_created': {
      if (state.stage !== 'create') return state;
      return {
        stage: 'locator',
        draft: {
          ...state.draft,
          sourceId: action.sourceId,
          sourceName: action.sourceName,
          sourceType: action.sourceType,
          skipLocator: action.skipLocator,
        },
        ready: action.skipLocator,
      };
    }

    case 'locator_submitted': {
      if (state.stage !== 'locator') return state;
      return {
        ...state,
        draft: { ...state.draft, locator: action.locator },
        ready: true,
      };
    }
  }
}
