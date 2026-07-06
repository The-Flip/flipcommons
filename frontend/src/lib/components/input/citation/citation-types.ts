/** Types, pure helpers and the state-machine reducer for the citation flow. */
import type {
  CitationInstanceSchema,
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
 *  - `name`: manual text — the authored-work form (book/magazine type picker), unless a parent locks the type.
 *  - `extraction`: a scraped book/magazine draft (from an ISBN) — the authored-work form, fields prefilled.
 *  - `web`: a pasted web URL — the web flow. `siteName` non-null means the site already exists
 *    (Create Site is skipped, it names that site); null means a new site (Create Site shown). `draft`
 *    is the page scrape (page name + site name prefill, URL confirmed read-only) or null when the
 *    scrape failed/was skipped (URL stays editable, nothing prefilled). `pageName` prefills the page
 *    name when there's no scrape — used by the manual "add a page under a known site" path. */
export type CreateSeed =
  | { kind: 'name'; name: string }
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

/** An unsaved draft of a CitationInstance.  Accumulates across stages: search sets sourceId, identify may change it, the locator stage sets locator and quote.
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
  quote: string;
};

/** A finished draft: the source is chosen (non-null) and the locator entered.
 * The content-spec completion hands this to the consumer instead of a minted
 * instance. */
export type CompletedCitationDraft = {
  sourceId: number;
  sourceName: string;
  locator: string;
};

/** What the citation flow does on completion. Inline `[[cite:slug]]` cites
 * mint the instance eagerly — the editor needs its slug for the marker — and
 * receive it (`mint-instance`). Edit cites need no instance yet: the content
 * spec rides the save payload's `citations` list and the backend mints at
 * save time (`content-spec`). */
export type CitationCompletion =
  | { kind: 'mint-instance'; oncomplete: (instance: CitationInstanceSchema) => void }
  | { kind: 'content-spec'; oncomplete: (draft: CompletedCitationDraft) => void };

/** Per-flow configuration, seeded once at flow init and passed to every
 *  `transition`. `collectsQuote` is true for the inline (`mint-instance`) flow,
 *  whose locator stage also collects an optional verbatim quote — the instance
 *  mints (immutably) the moment the flow completes, so the picker is the
 *  quote's only chance to exist. The edit (`content-spec`) flow collects its
 *  quote later, on the edit panel (`EditCitationField`), and never shows it
 *  here. */
export type CiteFlowConfig = {
  collectsQuote: boolean;
};

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
  /** Source is chosen. User refines the minted instance's fields — an optional
   *  locator (page number, start time, etc.) and, when the flow collects one
   *  (`CiteFlowConfig.collectsQuote`), an optional quote. A skip-locator
   *  source hides the locator input, leaving a quote-only screen.
   *
   *  `ready` marks completion: the reducer has everything it needs and the
   *  orchestrator should submit the draft. The stage stays `locator` rather
   *  than switching to a bare terminal because submission is an async POST
   *  that can fail — the populated screen must stay rendered so a failure
   *  shows in place. `ready` is set with the stage never rendered at all when
   *  a flow that collects no quote resolves a skip-locator source. */
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
  /** User submitted or skipped the locator stage. Carries both of that
   *  screen's fields; `quote` is always `''` for flows that don't collect one. */
  | { type: 'locator_submitted'; locator: string; quote: string };

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
    quote: '',
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

/** Whether a just-resolved source completes the flow with no locator screen.
 *  Only a flow that collects no quote can finish here: a quote-collecting
 *  (inline) flow always renders the locator stage, even for a skip-locator
 *  source, where it shows as a quote-only screen. */
function readyOnSourceResolution(config: CiteFlowConfig, skipLocator: boolean): boolean {
  return skipLocator && !config.collectsQuote;
}

/** Invalid action/state combos return current state unchanged.
 *
 * The reducer owns stage sequencing end to end — including the skip-locator
 * shortcut and flow completion (the `ready` marker on the locator state) — so
 * the orchestrator submits exactly when told, never by sniffing the draft. */
export function transition(
  state: CiteState,
  action: CiteAction,
  config: CiteFlowConfig,
): CiteState {
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
        ready: readyOnSourceResolution(config, action.source.skip_locator),
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
        ready: readyOnSourceResolution(config, action.skipLocator),
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
        ready: readyOnSourceResolution(config, action.skipLocator),
      };
    }

    case 'locator_submitted': {
      if (state.stage !== 'locator') return state;
      return {
        ...state,
        draft: { ...state.draft, locator: action.locator, quote: action.quote },
        ready: true,
      };
    }
  }
}
