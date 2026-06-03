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

/** Subset of a search result carried through the state machine after selecting an abstract source. */
export type ParentContext = {
  id: number;
  name: string;
  source_type: string;
  author: string;
  identifier_key: string;
};

/** An unsaved draft of a CitationInstance.  Accumulates across stages: search sets sourceId, identify may change it, locator sets locator. */
export type CitationInstanceDraft = {
  sourceId: number | null;
  sourceName: string;
  locator: string;
  skipLocator: boolean;
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
  /** User is creating a new source manually (or from an extraction draft). */
  | {
      stage: 'create';
      draft: CitationInstanceDraft;
      parent: ParentContext | null;
      prefillName: string;
      extractionDraft: ExtractionDraft | null;
    }
  /** Source is chosen. User enters an optional locator (page number, URL fragment, etc.). */
  | { stage: 'locator'; draft: CitationInstanceDraft };

/** Inputs to the state machine, dispatched by stage components via the orchestrator. */
export type CiteAction =
  /** User picked a source from search results. Abstract → identify; concrete → locator. */
  | { type: 'source_selected'; source: CitationSourceResult }
  /** The exact citable CitationSource is known (via URL recognition, child selection, etc.). → locator. */
  | { type: 'source_identified'; sourceId: number; sourceName: string; skipLocator: boolean }
  /** User wants to create a new CitationSource. → create. */
  | { type: 'source_create_started'; prefillName: string }
  /** Extraction API returned a draft for user confirmation. → create (prefilled). */
  | { type: 'extraction_draft_ready'; extractionDraft: ExtractionDraft }
  /** New CitationSource was created via API. → locator. */
  | { type: 'source_created'; sourceId: number; sourceName: string; skipLocator: boolean }
  /** User submitted or skipped the locator. */
  | { type: 'locator_submitted'; locator: string };

// ---------------------------------------------------------------------------
// Pure functions
// ---------------------------------------------------------------------------

export function suppressChildResults(results: CitationSourceResult[]): CitationSourceResult[] {
  const resultIds = new Set(results.map((r) => r.id));
  return results.filter((r) => !r.parent_id || !resultIds.has(r.parent_id));
}

export function isDraftSubmittable(draft: CitationInstanceDraft): boolean {
  return draft.sourceId !== null && (draft.locator.length > 0 || draft.skipLocator);
}

export function emptyDraft(): CitationInstanceDraft {
  return { sourceId: null, sourceName: '', locator: '', skipLocator: false };
}

// ---------------------------------------------------------------------------
// Child creation by identifier
// ---------------------------------------------------------------------------

export type CreateByIdentifierResult =
  | { ok: true; sourceId: number; sourceName: string; skipLocator: boolean }
  | { ok: false; error: string };

/** Create a child source under a parent using a structured identifier.
 *  The backend validates the identifier, auto-builds the name and canonical URL. */
export async function createChildByIdentifier(
  apiClient: ApiClient,
  parentId: number,
  parentName: string,
  sourceType: string,
  identifier: string,
): Promise<CreateByIdentifierResult> {
  const { data, error } = await apiClient.POST('/api/citation-sources/', {
    body: {
      name: `${parentName} #${identifier}`,
      source_type: sourceType,
      author: '',
      publisher: '',
      date_note: '',
      description: '',
      parent_id: parentId,
      identifier,
      link_label: '',
      link_type: 'homepage',
    },
  });
  if (error) {
    return { ok: false, error: typeof error === 'string' ? error : 'Invalid identifier.' };
  }
  return { ok: true, sourceId: data.id, sourceName: data.name, skipLocator: data.skip_locator };
}

// ---------------------------------------------------------------------------
// State machine
// ---------------------------------------------------------------------------

export function parentContextFromSource(source: CitationSourceResult): ParentContext {
  return {
    id: source.id,
    name: source.name,
    source_type: source.source_type,
    author: source.author,
    identifier_key: source.identifier_key,
  };
}

/** Invalid action/state combos return current state unchanged. */
export function transition(state: CiteState, action: CiteAction): CiteState {
  switch (action.type) {
    case 'source_selected': {
      if (state.stage !== 'search') return state;
      const draft = { ...state.draft, sourceId: action.source.id, sourceName: action.source.name };
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
          skipLocator: action.skipLocator,
        },
      };
    }

    case 'source_create_started': {
      if (state.stage !== 'search' && state.stage !== 'identify') return state;
      return {
        stage: 'create',
        draft: state.draft,
        parent: state.stage === 'identify' ? state.parent : null,
        prefillName: action.prefillName,
        extractionDraft: null,
      };
    }

    case 'extraction_draft_ready': {
      if (state.stage !== 'search') return state;
      return {
        stage: 'create',
        draft: state.draft,
        parent: null,
        prefillName: action.extractionDraft.name,
        extractionDraft: action.extractionDraft,
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
          skipLocator: action.skipLocator,
        },
      };
    }

    case 'locator_submitted': {
      if (state.stage !== 'locator') return state;
      return {
        ...state,
        draft: { ...state.draft, locator: action.locator },
      };
    }
  }
}
